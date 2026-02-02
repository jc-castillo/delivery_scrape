rm(list = ls())

library(arrow)
library(data.table)
library(fixest)
library(ggplot2)
library(duckdb)
library(DBI)

d <- read_parquet("~/Documents/delivery_scrape/data/summary/summary_by_crawl_platform_city.parquet")
setDT(d)

setkey(d, crawl_id, city, platform)

View(d[city=="Madrid"])