import psycopg2
from config.settings import DB_CONFIG

def run_query(sql: str):
    """Run a SQL query and print the results"""
    conn = psycopg2.connect(
        host=DB_CONFIG['host'],
        port=DB_CONFIG['port'],
        database=DB_CONFIG['database'],
        user=DB_CONFIG['user'],
        password=DB_CONFIG['password']
    )
    cursor = conn.cursor()
    try:
        cursor.execute(sql)
        results = cursor.fetchall()
        col_names = [desc[0] for desc in cursor.description]
        
        # print column headers
        print(" | ".join(col_names))
        print("-" * 80)
        
        # print each row
        for row in results:
            print(" | ".join(str(val) for val in row))
            
        print(f"\n{len(results)} rows returned")
    except Exception as e:
        print(f"Query failed: {e}")
    finally:
        cursor.close()
        conn.close()


# put your queries here
if __name__ == "__main__":
    run_query("SELECT * FROM games;")
    run_query("SELECT COUNT(*) FROM box_scores_players;")
    run_query("SELECT COUNT(*) FROM play_by_play;")
    run_query("SELECT COUNT(*) FROM advanced_boxscore_players;")