import sqlite3
import logging
import uuid

logging.basicConfig(level=logging.INFO)

def generate_ID() -> str:
    return str(uuid.uuid4())

class Database:
    def __init__(self, file: str = "data.db"):
        self.file = file
        self.conn_db = None
        self.cursor = None

    def connect(self):
        self.conn_db = sqlite3.connect(self.file, check_same_thread=False)
        self.cursor = self.conn_db.cursor()

        # ATIVA FOREIGN KEYS
        self.cursor.execute("PRAGMA foreign_keys = ON")

    def close(self):
        if self.conn_db:
            self.conn_db.close()

        self.conn_db = None
        self.cursor = None

    def cmd(self, command, action: str = 'commit'):
        try:
            self.connect()
            self.cursor.execute(command)

            if action == "fetchone":
                return True, self.cursor.fetchone()

            elif action == "fetchall":
                return True, self.cursor.fetchall()

            else:
                self.conn_db.commit()
                return True, None

        except Exception as err:
            logging.error(f"Erro SQL: {err}")
            return False, str(err)

        finally:
            self.close()

    def create_tables(self):
        logging.info("Criando tabelas...")

        self.cmd('''
            CREATE TABLE IF NOT EXISTS companies (
                company_id TEXT PRIMARY KEY,
                company_name TEXT NOT NULL UNIQUE,
                auth_key TEXT NOT NULL UNIQUE,
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        ''')

        self.cmd('''
            CREATE TABLE IF NOT EXISTS printers (
                printer_id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,

                hostname TEXT,
                last_ip TEXT,

                status TEXT NOT NULL DEFAULT 'offline',
                status_payload TEXT,

                last_connected_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now')),

                FOREIGN KEY (company_id)
                    REFERENCES companies(company_id)
                    ON DELETE CASCADE
                    ON UPDATE CASCADE
            )
        ''')

        self.cmd('''
            CREATE INDEX IF NOT EXISTS idx_printers_company
            ON printers(company_id)
        ''')

        self.cmd('''
            CREATE INDEX IF NOT EXISTS idx_printers_status
            ON printers(status)
        ''')

        self.cmd('''
            CREATE INDEX IF NOT EXISTS idx_printers_last_seen
            ON printers(last_connected_at)
        ''')

        logging.info("Tabelas criadas com sucesso")


if __name__ == "__main__":
    db = Database()
    db.create_tables()
