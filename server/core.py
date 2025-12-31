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

    def company_verify(self, company_id):
        status, _ = self.cmd('SELECT company_id FROM companies WHERE company_id = ?', (company_id,), "fetchone")

        if status:
            return True, None

        return False, _

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

    def company_get_data(self, company_id):
        status, _ = self.company_verify(company_id)
        if not status:
            return _

        status_comp, data_comp = self.cmd(
            """
                SELECT 
                    company_name, auth_key, status, created_at
                FROM 
                    companies 
                WHERE 
                    company_id = ?
            """,
            (company_id,),
            action="fetchone"
        )

        if not status_comp:
            return status_comp, data_comp

        status_print, data_print = self.cmd(
            """
                SELECT 
                    printer_id, client_id, last_ip, status, status_payload, last_connected_at, created_at 
                FROM 
                    printers 
                WHERE 
                    company_id = ?
            """,
            arguments=(company_id,),
            action="fetchall"
        )

        if not status_print:
            return status_print, data_print

        data_result = {
            "company": {
                "id": company_id,
                "name": data_comp[0],
                "auth_key": data_comp[1],
                "status": data_comp[2],
                "created_at": data_comp[3]
            },
            "printers" : []
        }

        for printer in data_print:
            data_result['printers'].append(
                {
                    "id": printer[0],
                    "client_id": printer[1],
                    "last_ip": printer[2],
                    "status": printer[3],
                    "status_payload": printer[4],
                    "last_connection": printer[5],
                    "created_at": printer[6] 
                }
            )

        return True, data_result

    def printer_register(self, company_id:str, last_ip:str=""):
        client_id = generate_id()

        return self.cmd(
            command="""
            INSERT INTO printers 
                (company_id, client_id, last_ip) 
            VALUES 
                (?, ?, ?)
            """,
            arguments=(company_id, client_id, last_ip,)
        )

# +=====================+
# |                     |
# |  _____         _    |
# | |_   _|__  ___| |_  |
# |   | |/ _ \/ __| __| |
# |   | |  __/\__ \ |_  |
# |   |_|\___||___/\__| |
# |                     |
# +=====================+
if __name__ == "__main__":
    api_core = APICore()
    
    # print(api_core.company_register("Thenorian"))
    # print(api_core.companies_all_list())
    # print(api_core.printer_register("2aa2e597-faa9-42f8-8b6d-d1df62545571"))
    # print(api_core.company_get_data("2aa2e597-faa9-42f8-8b6d-d1df62545571"))