import sqlite3
conn = sqlite3.connect('devplane.db')
c = conn.cursor()
c.execute('PRAGMA table_info(droplets)')
rows = c.fetchall()
for row in rows:
    print(row)
c.execute('SELECT COUNT(*) FROM droplets')
print('Row count:', c.fetchone()[0])
conn.close()