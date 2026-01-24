-- 🚀 Odos System Test Setup Script
-- Run this in your Snowflake Worksheet to create the playground environment.

-- 1. Create a Dedicated Warehouse (Low Cost)
CREATE WAREHOUSE IF NOT EXISTS odos_test_wh 
WITH WAREHOUSE_SIZE = 'XSMALL' 
AUTO_SUSPEND = 60 
AUTO_RESUME = TRUE;

-- 2. Create the Database & Schema
CREATE DATABASE IF NOT EXISTS odos_demo;
CREATE SCHEMA IF NOT EXISTS odos_demo.raw;
USE SCHEMA odos_demo.raw;

-- 3. Create "Ghost Table" Candidate (Large, Unused)
-- We simulate size by creating a table, but we can't fake the "Active Bytes" metadata easily without loading real data.
-- However, we can create the structure.
CREATE TABLE IF NOT EXISTS marketing_campaign_logs_legacy (
    event_id VARCHAR,
    payload VARIANT,
    ingested_at TIMESTAMP
);
-- Add a comment so we know it's a test object
COMMENT ON TABLE marketing_campaign_logs_legacy IS 'Simulated Ghost Table for Odos Storage Advisor';

-- 4. Create "Cold Data" Candidate
CREATE TABLE IF NOT EXISTS web_events_2023 (
    user_id VARCHAR,
    url VARCHAR,
    event_ts TIMESTAMP
);

-- 5. Create "Clustering Opportunity" (Full Scan Candidate)
CREATE TABLE IF NOT EXISTS engineering_logs_unclustered (
    log_level VARCHAR,
    message VARCHAR,
    log_ts TIMESTAMP
);

-- 6. Insert dummy data (Optional, metadata updates take 1-2 hours)
INSERT INTO engineering_logs_unclustered 
SELECT 'INFO', 'System start', DATEADD(hour, -seq4(), CURRENT_TIMESTAMP())
FROM TABLE(GENERATOR(ROWCOUNT => 1000));

-- 7. Grant Privileges (Critical for the Tool to work)
-- The Odos user needs permission to READ metadata.
GRANT USAGE ON WAREHOUSE odos_test_wh TO ROLE ACCOUNTADMIN;
GRANT USAGE ON DATABASE odos_demo TO ROLE ACCOUNTADMIN;
GRANT USAGE ON SCHEMA odos_demo.raw TO ROLE ACCOUNTADMIN;
GRANT SELECT ON ALL TABLES IN SCHEMA odos_demo.raw TO ROLE ACCOUNTADMIN;

-- NOTE: The Storage Advisor queries 'SNOWFLAKE.ACCOUNT_USAGE'.
-- This usually requires ACCOUNTADMIN or a role with specific GOVERNANCE privileges.