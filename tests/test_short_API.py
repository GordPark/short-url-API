import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from redis import Redis
from app.short_API import app, Base, get_db, get_redis_client, URL_Mapping
import time
import fakeredis

# 테스트용 SQLite DB 설정
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Redis 클라이언트 목업 설정 (테스트용 Redis 설정)
redis_test_client = Redis(host='localhost', port=6379, db=1)

# Redis 클라이언트 오버라이드
def override_redis_client():
    return fakeredis.FakeRedis()  # FakeRedis로 Redis 모킹

# 의존성 주입을 위해 DB 세션 및 Redis 클라이언트를 오버라이드
def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()



# DB와 Redis 초기화
Base.metadata.create_all(bind=engine)
app.dependency_overrides[get_db] = override_get_db
app.dependency_overrides[get_redis_client] = override_redis_client

client = TestClient(app)

@pytest.fixture(scope="function", autouse=True)
def setup_and_teardown():
    # 테스트 전후로 DB 초기화
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    redis_test_client.flushdb()  # 테스트용 Redis 초기화
    yield

# FakeRedis 연결확인
def test_redis_connection():
    redis_client = override_redis_client()
    redis_client.set("test_key", "test_value")
    assert redis_client.get("test_key") == b"test_value"


# 단축 URL 생성 테스트
def test_shorten_url():
    response = client.post("/shorten/", json={"url": "https://www.naver.com", "expiry": 60})
    assert response.status_code == 200
    assert "short_url" in response.json()
    short_url = response.json()["short_url"]
    assert short_url.startswith("http://localhost:8700/")

# 리디렉션 테스트
def test_redirect_url():
    response = client.post("/shorten/", json={"url": "https://www.naver.com", "expiry": 60})
    short_url = response.json()["short_url"].split("/")[-1]
    
    # 리디렉션 엔드포인트 호출
    response = client.get(f"/{short_url}/")
    print(response.json())  # 디버깅 출력
    assert response.status_code == 301
    assert response.headers["Location"] == "https://www.naver.com"

# 만료된 URL 처리 테스트
def test_url_expiry():
    # 짧은 만료 시간으로 단축 URL 생성
    response = client.post("/shorten/", json={"url": "https://www.naver.com", "expiry": 1})
    short_url = response.json()["short_url"].split("/")[-1]
    
    # 바로 리디렉션 테스트 (성공해야 함)
    response = client.get(f"/{short_url}/")
    assert response.status_code == 301
    
    # 만료 후 테스트 (404 응답 예상)
    time.sleep(2)  # 1초 sleep (만료 시간)
    response = client.get(f"/{short_url}/")
    print(response.json())  # 디버깅 출력
    assert response.status_code == 404
    assert response.json()["detail"] == "URL expired"

# 통계 조회 테스트
def test_get_stats():
    response = client.post("/shorten/", json={"url": "https://www.naver.com", "expiry": 60})
    short_url = response.json()["short_url"].split("/")[-1]
    
    # 리디렉션 엔드포인트 호출
    client.get(f"/{short_url}/")
    client.get(f"/{short_url}/")
    
    # 조회 수 통계 확인
    response = client.get(f"/stats/{short_url}")
    assert response.status_code == 200
    assert response.json()["hits"] == 2
