#!/usr/bin/env python3
import typer

from commands import database, logs, server, sites, ssl, users

app = typer.Typer(name="panel", help="Hosting panel — manage users, sites, SSL, and databases.")

# User management
app.command("create-user")(users.create_user)
app.command("delete-user")(users.delete_user)
app.command("list-users")(users.list_users)

# Site management
app.command("add-site")(sites.add_site)
app.command("delete-site")(sites.delete_site)
app.command("list-sites")(sites.list_sites)
app.command("disable-site")(sites.disable_site)
app.command("enable-site")(sites.enable_site)
app.command("set-php")(sites.set_php)

# SSL
app.command("issue-ssl")(ssl.issue_ssl)

# Database
app.command("create-db")(database.create_db)
app.command("delete-db")(database.delete_db)
app.command("list-dbs")(database.list_dbs)

# Logs
app.command("logs")(logs.logs)

# Server bootstrap
app.command("init-server")(server.init_server)

if __name__ == "__main__":
    app()
