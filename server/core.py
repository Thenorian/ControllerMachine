from database import *
import socket
import threading
import json
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

class APICore(Database):
    def __init__(self):
        super().__init__()

    def companies_all_list(self):
        return self.cmd("""
                SELECT * 
                FROM companies
                WHERE status = 'active'
            """, 
            action="fetchall"
        )

    def company_register(self, company_name: str):
        company_id = generate_id()
        auth_key = generate_id()

        status, error = self.cmd(
            command="""
                INSERT INTO companies 
                    (company_id, company_name, auth_key) 
                VALUES 
                    (?, ?, ?)
            """,
            arguments=(company_id, company_name, auth_key),
        )

        if not status:
            return False, error

        return True, {
            "company_id": company_id,
            "auth_key": auth_key
        }

    def company_get(self, company_id):
        return self.cmd(
            "SELECT * FROM companies WHERE company_id = ?",
            (company_id,),
            action="fetchone"
        )

if __name__ == "__main__":
    api_core = APICore()
    print(api_core.company_register("Thenorian"))
    print(api_core.companies_all_list())
