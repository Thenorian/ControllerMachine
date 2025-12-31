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

    def company_get_data(self, company_id):
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

        status_print, data_print = self.cmd(
            """
                SELECT 
                    printer_id, hostname, last_ip, status, status_payload, last_connected_at, created_at 
                FROM 
                    printers 
                WHERE 
                    company_id = ?
            """,
            arguments=(company_id,),
            action="fetchall"
        )

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
                    "id": data_print[0],
                    "hostname": data_print[1],
                    "last_ip": data_print[2],
                    "status": data_print[3],
                    "status_payload": data_print[4],
                    "last_connection": data_print[5],
                    "created_at": data_print[6] 
                }
            )

        if not status_comp:
            return status_comp, data_comp

        elif not status_print:
            return status_print, data_print

        return True, data_result

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
    print(api_core.company_get_data("92a6259b-80c0-4633-be2a-d81a44e85a6e"))