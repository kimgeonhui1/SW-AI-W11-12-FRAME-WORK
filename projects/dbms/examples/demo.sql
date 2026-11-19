-- 미니 DBMS 데모. projects/dbms 폴더에서: python -m minidb examples/demo.sql
-- 테이블은 data/schema.json에 이미 있다고 가정한다 (CREATE TABLE 없음)

INSERT INTO users (name, age) VALUES ('홍길동', 25);
INSERT INTO users VALUES ('lee, "jr"', 30);              -- 컬럼 목록 없이: 스키마 순서대로
insert into users (age, name) values (41, 'it''s me');   -- 소문자 키워드, 순서 바꾼 컬럼, 따옴표 넣기
INSERT INTO products (title, price) VALUES ('키보드', 50000);

SELECT * FROM users;
SELECT name FROM users WHERE age = 30;
SELECT title, price FROM products
