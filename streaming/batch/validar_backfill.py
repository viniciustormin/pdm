"""Compara a contagem por ano: API oficial x bronze nova x bronze antiga do T1.
Uso (Cloud Shell): python3 validar_backfill.py
"""
import requests
from google.cloud import bigquery

API = "https://data.cityofchicago.org/resource/ijzp-q8t2.json"
bq = bigquery.Client(project="pdm-crimes-chicago")

api = {int(r["year"]): int(r["n"]) for r in requests.get(
    API, params={"$select": "year, count(*) AS n", "$group": "year", "$order": "year"},
    timeout=120).json()}
nova = {r.ano: r.n for r in bq.query("""
  SELECT SAFE_CAST(year AS INT64) AS ano, COUNT(DISTINCT id) AS n
  FROM `crimes_chicago.tb_crimes_bronze_api` GROUP BY 1""").result()}
antiga = {r.ano: r.n for r in bq.query("""
  SELECT year AS ano, COUNT(DISTINCT unique_key) AS n
  FROM `crimes_chicago.tb_crimes_bronze` GROUP BY 1""").result()}

print(f"{'ano':>4} | {'API':>9} | {'bronze_api':>10} | {'dif':>6} | {'bronze_T1':>9}")
print("-" * 52)
tot = [0, 0, 0]
for ano in sorted(set(api) | set(nova)):
    a, n, o = api.get(ano, 0), nova.get(ano, 0), antiga.get(ano, 0)
    tot = [tot[0] + a, tot[1] + n, tot[2] + o]
    flag = "" if a == n else "  <--"
    print(f"{ano:>4} | {a:>9,} | {n:>10,} | {n - a:>6,} | {o:>9,}{flag}")
print("-" * 52)
print(f"{'tot':>4} | {tot[0]:>9,} | {tot[1]:>10,} | {tot[1]-tot[0]:>6,} | {tot[2]:>9,}")
