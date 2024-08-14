# short-url-API

# 개요

이 프로젝트는 FastAPI를 사용하여 URL 단축 서비스를 구현한 것입니다. 사용자는 긴 URL을 고유한 단축 키로 변환하고, 이 단축 키를 통해 원본 URL로 리디렉션할 수 있습니다. 또한, URL 만료 기능과 단축 URL의 조회 수를 추적하는 기능도 지원합니다.

## 기능

1. **단축 URL 생성**:

   - **엔드포인트**: `POST /shorten/`
   - **요청 본문**:
     ```json
     {
       "url": "<original_url>",
       "expiry": <expiry_seconds> // 선택 사항
     }
     ```
   - **응답 본문**:
     ```json
     {
       "short_url": "<shortened_url>"
     }
     ```

2. **URL 리디렉션**:

   - **엔드포인트**: `GET /{short_key}/`
   - **응답**:
     - `301 Moved Permanently`: 단축 키가 유효할 경우
     - `404 Not Found`: 단축 키가 존재하지 않거나 만료된 경우

3. **URL 통계**:
   - **엔드포인트**: `GET /stats/{short_key}/`
   - **응답**:
     ```json
     {
       "short_key": "<short_key>",
       "hits": <number_of_accesses>
     }
     ```

### 단축 키 생성

단축 키는 HMAC (Hash-based Message Authentication Code) SHA-256을 사용하여 생성.

1. **데이터 준비**:

   - URL, 현재 타임스탬프, 만료 시간을 결합하여 데이터 문자열을 생성.

2. **HMAC 계산**:

   - 생성된 데이터를 `SECRET_KEY`와 함께 HMAC-SHA256 해시 함수를 사용하여 해시 값을 계산. 이 해시는 32바이트(256비트) 길이의 바이트 문자열.

3. **Base62 인코딩**:

   - HMAC 해시의 상위 5바이트를 정수로 변환.
   - 이 정수(40비트 길이)를 Base62 인코딩하여 길이 8자의 단축 키를 생성.
   - Base62는 알파벳 대문자, 소문자, 숫자 총 62개 문자를 사용하여 정수(40비트 길이)를 문자로 변환.

   이 방법은 고유성과 보안을 보장하면서 단축 키 생성. Base62 인코딩은 URL에서의 사용 용이성과 압축성을 고려하여 선택.

### URL 만료

만료 시간이 지정된 URL을 단축할 때, 시스템은 데이터베이스에 만료. 타임스탬프를 저장하고 리디렉션 요청이 들어올 때마다 만료 시간을 확인하며, URL이 만료되었으면 `404 Not Found`를 반환.

## 기술 스택

- **백엔드**: FastAPI
- **데이터베이스**: SQLite, Postgresql
- **캐시**: Redis (테스트에서는 `fakeredis` 사용)

## DB 선택 이유

Postgresql - 뛰어난 신뢰성과 확장성을 제공하고 대규모 DB와 트래픽을 처리하는 데 효과적. 그리고 JSON, 배열, 지리공간 데이터 등 다양한 데이터 타입을 지원하여 유연한 데이터 모델링이 가능하여 short_API 앱에 적용

Redis - 읽기 및 쓰기 성능이 매우 빠름 > 실시간 데이터 처리 및 캐싱에 적합,
캐싱 용도로 사용하여 DB조회 결과를 캐싱하여 DB의 부하를 줄이고 응답 속도 향상
조회 수와 같은 자주 액세스 되는 데이터를 저장하는데 적합

SQLite - 가벼운 관계형 DB,서버를 설치할 필요 없이 로컬 파일 시스템에 DB를 저장 > 테스트 및 개발 환경에서 쉽게 사용가능
테스트 코드 작성에 사용

## 실행 방법

1. **환경 설정**:

   - `.env` 파일에 `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`을 설정합니다.

     _DB 설정 연결하려는 DB로 변경해야됨_
     SECRET_KEY=my_secret_key
     DATABASE_URL=postgresql+psycopg2://ryong:1234@localhost/mydatabase

   REDIS_URL=redis://localhost:6379/0

2. **라이브러리 설치**:

   ```bash
   pip install -r requirements.txt
   ```

3. **실행**:

   - 레디스 서버 실행
     redis-server

   - FastAPI 서버 실행
     uvicorn app.short_API:app --reload --port 8700

## 테스트 코드 에러

단축 URL을 통해 원래 URL로 리디렉션하는 과정에서 404코드 에러

# 리디렉션 테스트

test_redirect_url - assert 404 == 301

# 만료된 URL 처리 테스트

test_url_expiry - assert 404 == 301

test 코드에 원본 url 문제인지 확인
http://example.com

> > https://www.naver.com
> > 실제 연결이 가능한 url 수정 DB확인

단축키가 생성이되고 testDB에 저장이 되는데도 404로 리디렉션이 안됨
