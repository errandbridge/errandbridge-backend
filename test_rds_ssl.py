import asyncpg
import ssl

RDS_HOST = "errandbridge-dev-postgres.cexe0ua8g55s.us-east-1.rds.amazonaws.com"
RDS_PORT = 5432
RDS_DB = "errandbridge"
RDS_USER = "postgres"
RDS_PASSWORD = "postgres"  # Replace with your actual password if different

ssl_context = ssl.create_default_context(cafile="rds-global-bundle.pem")
ssl_context.check_hostname = True

async def main():
    try:
        conn = await asyncpg.connect(
            user=RDS_USER,
            password=RDS_PASSWORD,
            database=RDS_DB,
            host=RDS_HOST,
            port=RDS_PORT,
            ssl=ssl_context
        )
        print("Connected to RDS with SSL!")
        result = await conn.fetchval("SELECT 1;")
        print("Query result:", result)
        await conn.close()
    except Exception as e:
        print("Connection failed:", e)

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
