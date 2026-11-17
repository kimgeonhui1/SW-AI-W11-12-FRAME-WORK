-- Phase 1 시연: 파일 기반 INSERT · SELECT
-- 실행: projects/dbms 에서  python -m mini_dbms examples/phase1.sql

INSERT INTO users (name, age, email) VALUES ('김준우', 25, 'kim@example.com');
INSERT INTO users (name, age, email) VALUES
  ('O''Brien', 31, 'ob@example.com'),   -- 작은따옴표는 두 번
  ('이영희', NULL, 'lee@example.com');
INSERT INTO products VALUES ('키보드', 39000.5), ('마우스', 15000);   /* 열 목록 생략 = 스키마 순서 */

SELECT * FROM users;
SELECT name, age FROM users WHERE age >= 30;
SELECT * FROM users WHERE id = 2;                 -- B+ 트리 인덱스
SELECT * FROM products WHERE price < 20000 ORDER BY price DESC;
EXPLAIN SELECT * FROM users WHERE name = '김준우';  -- 계획만 (선형 탐색)
