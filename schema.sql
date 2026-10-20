CREATE DATABASE IF NOT EXISTS traffic_news_assignment CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE traffic_news_assignment;
CREATE TABLE IF NOT EXISTS traffic_facts (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 origin VARCHAR(100) NOT NULL,
 destination VARCHAR(100) NOT NULL,
 distance_m INT NOT NULL,
 duration_seconds INT NOT NULL,
 retrieved_at DATETIME NOT NULL,
 source_url VARCHAR(500) NOT NULL,
 CHECK(distance_m > 0), CHECK(duration_seconds >= 0)
);
CREATE TABLE IF NOT EXISTS news_drafts (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 fact_id BIGINT NOT NULL,
 title VARCHAR(255) NOT NULL,
 body TEXT NOT NULL,
 status ENUM('review','approved','held') NOT NULL DEFAULT 'review',
 created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (fact_id) REFERENCES traffic_facts(id) ON DELETE RESTRICT
);
CREATE TABLE IF NOT EXISTS draft_reviews (
 id BIGINT AUTO_INCREMENT PRIMARY KEY,
 draft_id BIGINT NOT NULL,
 passed BOOLEAN NOT NULL,
 reviewer_note TEXT NOT NULL,
 reviewed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY (draft_id) REFERENCES news_drafts(id) ON DELETE RESTRICT
);
