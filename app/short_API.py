from fastapi import FastAPI, Depends, HTTPException
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, Integer, String
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import Session
from urllib.parse import urlparse
import redis
import hmac
import hashlib
import time
import os
from dotenv import load_dotenv

# .env 파일 로드
load_dotenv()
# DB, 엔진 생성
SECRET_KEY = os.getenv("SECRET_KEY", "default_secret_key")
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

engine = create_engine(DATABASE_URL, echo=True) # echo 디버깅용 서비스 = False
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    
# 기본 클래스 생성
Base = declarative_base()

# 테이블 정의
class URL_Mapping(Base):
    __tablename__ = "url_mappings"
    id = Column(Integer, primary_key=True)
    short_key = Column(String, index=True) # 빠른검색
    original_url = Column(String, nullable=False)
    expiry = Column(Integer, nullable=True)  # 만료 시간 (타임스탬프)

class URL_Request(BaseModel):
    url: str
    expiry: int = None # 만료(초)
    
# 테이블 생성
Base.metadata.create_all(bind=engine)

app = FastAPI()
# CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 모든 도메인 허용
    allow_credentials=True,
    allow_methods=["*"],  # 모든 메소드 허용
    allow_headers=["*"],  # 모든 헤더 허용
)

# Redis 클라이언트 설정
def get_redis_client():
    try:
        return redis.Redis.from_url(REDIS_URL)
    except redis.ConnectionError as e:
        print(f"Redis connection error: {e}")
        raise HTTPException(status_code=500, detail="Redis connection error")
    
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# base62 인코딩
def base62(number, length=8):
    characters = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
    base = len(characters)
    result = ""
    while number > 0 and len(result) < length:
        result = characters[number % base] + result
        number = number // base
    
    # 패딩 추가 (길이를 고정)
    return result.rjust(length, '0')

def generate_hmac_base62(url, expiry=None):
    timestamp = str(int(time.time()))
    print("timestamp: ",timestamp)
    data = url + timestamp + (str(expiry) if expiry else "")
    print("data: ",data)
    
    # HMAC 생성 (SHA256 사용)
    hmac_hash = hmac.new(SECRET_KEY.encode(), data.encode(), hashlib.sha256).digest()
    print("hmac_hash: ",hmac_hash)
    
    # HMAC의 상위 5~6바이트만 사용하여 Base62 인코딩 (고유성을 위해 바이트 수 조절 가능)
    # 5바이트 = 40비트 (Base62로 약 7글자), 6바이트 = 48비트 (Base62로 약 8글자)
    hash_int = int.from_bytes(hmac_hash[:5], 'big')  # 상위 5바이트 사용
    print("hash_int: ",hash_int)
    
    short_key = base62(hash_int, length=8)
    
    return short_key

#  URL 유효성 검사
def is_valid_url(url: str) -> bool:
    parsed_url = urlparse(url)
    return bool(parsed_url.scheme) and bool(parsed_url.netloc)

# 단축 URL 생성
# POST /shorten: 입력받은 긴 URL을 고유한 단축 키로 변환하고 데이터베이스에 저장.
# 요청 본문: {"url": "<original_url>"}
# 응답 본문: {"short_url": "<shortened_url>"}

@app.post("/shorten/")
def shorten_url(request: URL_Request, db: Session = Depends(get_db)):
    if not is_valid_url(request.url):
        raise HTTPException(status_code=400, detail="Invalid URL")
    
    short_key = generate_hmac_base62(request.url, request.expiry)  # 새로운 키 생성

    # 중복 검사
    while db.query(URL_Mapping).filter(URL_Mapping.short_key == short_key).first():
        short_key = generate_hmac_base62(request.url, request.expiry)  # 새로운 키 생성
     
    # URL 매핑 데이터베이스에 저장
    expiry_timestamp = int(time.time()) + request.expiry if request.expiry else None
    db_url = URL_Mapping(short_key=short_key, original_url=request.url, expiry=expiry_timestamp)
    db.add(db_url)
    db.commit()

    # Redis 클라이언트 가져오기
    redis_client = get_redis_client()

    # Redis에 조회 수 초기화, 만료 시간 설정
    try:
        redis_client.setex(f"hits:{short_key}", request.expiry or 0 , 0)
        print(f"Redis key set: hits:{short_key} with expiry {request.expiry}")
    except Exception as e:
        print(f"Error setting Redis key: {e}")

    return {"short_url": f"http://localhost:8700/{short_key}"}
    

# 원본 URL 리디렉션
# GET /<short_key>: 단축된 키를 통해 원본 URL로 리디렉션.
# 응답:
# 키가 존재하면 301 상태 코드로 원본 URL로 리디렉션.
# 키가 존재하지 않으면 404 상태 코드로 오류 메시지 반환.
@app.get("/{short_key}/")
def redirect_url(short_key: str, db: Session = Depends(get_db)):
    redis_client = get_redis_client()
    # Redis에서 조회 수를 증가시키기 전에 URL이 만료되었는지 확인
    hits_key = f"hits:{short_key}"
    # 원본 URL 가져오기
    db_url = db.query(URL_Mapping).filter(URL_Mapping.short_key == short_key).first()

    if db_url:
            # 만료 시간 체크
        if db_url.expiry and int(time.time()) > db_url.expiry:
            # 만료된 URL 처리
            db.delete(db_url)
            db.commit()
            redis_client.delete(hits_key)  # Redis에서 삭제
            print(f"URL expired: {short_key}")
            raise HTTPException(status_code=404, detail="URL expired")
        else:
            # Redis에 조회 수 증가
            redis_client.incr(hits_key)
            # 리디렉션 응답 반환
            if not db_url.original_url.startswith(('http://', 'https://')):
                db_url.original_url = 'http://' + db_url.original_url  # Ensure URL has schema
            print(f"Redirecting to: {db_url.original_url}") 
            return RedirectResponse(url=db_url.original_url, status_code=301)
    else:
        print(f"URL not found: {short_key}")
        raise HTTPException(status_code=404, detail="URL not found")

@app.get("/stats/{short_key}/")
def get_stats(short_key: str, db: Session = Depends(get_db)):
    redis_client = get_redis_client()
     # Redis에서 조회 수 가져오기
    hits = redis_client.get(f"hits:{short_key}")

    if hits is None:
         # 데이터베이스에서 URL 매핑 확인
        db_url = db.query(URL_Mapping).filter(URL_Mapping.short_key == short_key).first()
        if not db_url:
            raise HTTPException(status_code=404, detail="Stats not found")
        hits = 0  # URL이 있지만 Redis에서 조회 수가 없는 경우
    
    return {"short_key": short_key, "hits": int(hits)}