"""NetPulse CLI.

Команды:
  ip                 — публичный IP, страна, провайдер (проверка VPN)
  ping HOST[:PORT]   — TCP-задержка (работает без прав администратора)
  dns DOMAIN         — разрешение домена в IPv4/IPv6
  tls DOMAIN         — срок действия TLS-сертификата
  sites              — доступность популярных сервисов (блокировки)
  report             — полный отчёт по всем проверкам
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import socket
import ssl
import statistics
import sys
import time
import urllib.request
from datetime import datetime, timezone

from . import __version__

DEFAULT_SITES = [
    "google.com", "youtube.com", "github.com", "telegram.org",
    "discord.com", "x.com", "instagram.com", "openai.com",
    "steamcommunity.com", "wikipedia.org", "cloudflare.com", "netflix.com",
]

USE_COLOR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else text


OK = lambda t: c(t, "32")      # noqa: E731
WARN = lambda t: c(t, "33")    # noqa: E731
BAD = lambda t: c(t, "31")     # noqa: E731
DIM = lambda t: c(t, "2")      # noqa: E731
BOLD = lambda t: c(t, "1")     # noqa: E731


# ---------------------------------------------------------------- checks

def public_ip(timeout: float = 5.0) -> dict:
    """Публичный IP и геоданные. Пробует несколько сервисов по очереди."""
    providers = [
        ("https://ipinfo.io/json", lambda d: {
            "ip": d.get("ip"), "country": d.get("country"), "city": d.get("city"),
            "org": d.get("org"), "timezone": d.get("timezone")}),
        ("https://ipwho.is/", lambda d: {
            "ip": d.get("ip"), "country": d.get("country_code"), "city": d.get("city"),
            "org": (d.get("connection") or {}).get("isp"),
            "timezone": (d.get("timezone") or {}).get("id")}),
        ("https://api.ipify.org?format=json", lambda d: {"ip": d.get("ip")}),
    ]
    last_err = None
    for url, parse in providers:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": f"netpulse/{__version__}"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = parse(json.loads(r.read().decode()))
                data["source"] = url.split("/")[2]
                return data
        except Exception as e:  # noqa: BLE001
            last_err = e
    return {"error": str(last_err)}


def tcp_ping(host: str, port: int = 443, count: int = 4, timeout: float = 3.0) -> dict:
    """Время установки TCP-соединения (мс)."""
    times, errors = [], []
    for _ in range(count):
        start = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=timeout):
                times.append((time.perf_counter() - start) * 1000)
        except OSError as e:
            errors.append(str(e))
    res = {"host": host, "port": port, "sent": count, "ok": len(times)}
    if times:
        res.update(min=min(times), avg=statistics.mean(times), max=max(times),
                   jitter=statistics.pstdev(times) if len(times) > 1 else 0.0)
    if errors:
        res["error"] = errors[-1]
    return res


def dns_lookup(domain: str) -> dict:
    try:
        infos = socket.getaddrinfo(domain, None)
    except socket.gaierror as e:
        return {"domain": domain, "error": str(e)}
    v4 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET})
    v6 = sorted({i[4][0] for i in infos if i[0] == socket.AF_INET6})
    return {"domain": domain, "ipv4": v4, "ipv6": v6}


def tls_info(domain: str, port: int = 443, timeout: float = 5.0) -> dict:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((domain, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=domain) as ss:
                cert = ss.getpeercert()
                version = ss.version()
    except Exception as e:  # noqa: BLE001
        return {"domain": domain, "error": str(e)}
    not_after = datetime.fromtimestamp(ssl.cert_time_to_seconds(cert["notAfter"]), tz=timezone.utc)
    issuer = dict(x[0] for x in cert.get("issuer", ()))
    return {
        "domain": domain, "tls": version,
        "issuer": issuer.get("organizationName") or issuer.get("commonName"),
        "expires": not_after.isoformat(),
        "days_left": (not_after - datetime.now(timezone.utc)).days,
    }


def site_check(domain: str, timeout: float = 5.0) -> dict:
    """DNS + TCP + TLS-рукопожатие: показывает, на каком этапе ломается доступ."""
    t0 = time.perf_counter()
    try:
        ip = socket.getaddrinfo(domain, 443, type=socket.SOCK_STREAM)[0][4][0]
    except socket.gaierror:
        return {"domain": domain, "status": "DNS", "detail": "домен не резолвится"}
    try:
        sock = socket.create_connection((ip, 443), timeout=timeout)
    except OSError:
        return {"domain": domain, "status": "TCP", "ip": ip, "detail": "нет TCP-соединения"}
    try:
        ctx = ssl.create_default_context()
        with ctx.wrap_socket(sock, server_hostname=domain):
            pass
    except ssl.SSLCertVerificationError:
        return {"domain": domain, "status": "CERT", "ip": ip, "detail": "подмена сертификата"}
    except Exception:  # noqa: BLE001
        return {"domain": domain, "status": "TLS", "ip": ip, "detail": "TLS сброшен (DPI?)"}
    finally:
        sock.close()
    return {"domain": domain, "status": "OK", "ip": ip,
            "ms": round((time.perf_counter() - t0) * 1000)}


# ---------------------------------------------------------------- printing

def print_ip(d: dict) -> None:
    print(BOLD("Публичный IP"))
    if "error" in d:
        print("  " + BAD(f"не удалось определить: {d['error']}"))
        return
    for k, label in [("ip", "IP"), ("country", "Страна"), ("city", "Город"),
                     ("org", "Провайдер"), ("timezone", "Часовой пояс")]:
        if d.get(k):
            print(f"  {label:<13} {d[k]}")
    sys_tz = time.strftime("%z")
    if d.get("timezone"):
        print(DIM(f"  Часовой пояс системы: UTC{sys_tz[:3]}:{sys_tz[3:]} — "
                  "если сильно отличается от пояса IP, сайты могут заподозрить VPN"))


def print_ping(d: dict) -> None:
    head = f"{d['host']}:{d['port']}"
    if not d["ok"]:
        print(f"  {head:<32} {BAD('недоступен')}  {DIM(d.get('error', ''))}")
        return
    avg = d["avg"]
    col = OK if avg < 80 else WARN if avg < 200 else BAD
    loss = 100 * (d["sent"] - d["ok"]) / d["sent"]
    print(f"  {head:<32} {col(f'{avg:6.1f} мс')}  min {d['min']:.1f} / max {d['max']:.1f} / "
          f"jitter {d['jitter']:.1f}  потери {loss:.0f}%")


def print_dns(d: dict) -> None:
    if "error" in d:
        print(f"  {d['domain']}: {BAD(d['error'])}")
        return
    print(f"  {d['domain']}")
    for ip in d["ipv4"]:
        print(f"    A     {ip}")
    for ip in d["ipv6"]:
        print(f"    AAAA  {ip}")


def print_tls(d: dict) -> None:
    if "error" in d:
        print(f"  {d['domain']}: {BAD(d['error'])}")
        return
    days = d["days_left"]
    col = OK if days > 30 else WARN if days > 7 else BAD
    print(f"  {d['domain']:<28} {d['tls']}  {d['issuer']}  истекает {d['expires'][:10]} "
          f"({col(f'{days} дн.')})")


def print_sites(rows: list[dict]) -> None:
    print(BOLD("Доступность сервисов"))
    for r in rows:
        if r["status"] == "OK":
            print(f"  {OK('●')} {r['domain']:<22} {r['ms']:>5} мс")
        else:
            print(f"  {BAD('●')} {r['domain']:<22} {BAD(r['status']):<5} {DIM(r['detail'])}")
    ok = sum(r["status"] == "OK" for r in rows)
    print(DIM(f"  Доступно {ok} из {len(rows)}"))


# ---------------------------------------------------------------- commands

def parse_target(t: str, default_port: int = 443) -> tuple[str, int]:
    if t.count(":") == 1:
        h, p = t.split(":")
        return h, int(p)
    return t, default_port


def run_sites(domains: list[str]) -> list[dict]:
    with cf.ThreadPoolExecutor(max_workers=16) as ex:
        return list(ex.map(site_check, domains))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="netpulse", description="Диагностика сети и VPN")
    p.add_argument("--json", action="store_true", help="вывод в JSON")
    p.add_argument("-V", "--version", action="version", version=f"netpulse {__version__}")
    sub = p.add_subparsers(dest="cmd")

    sub.add_parser("ip", help="публичный IP и геолокация")
    sp = sub.add_parser("ping", help="TCP-пинг")
    sp.add_argument("targets", nargs="+", help="host или host:port")
    sp.add_argument("-c", "--count", type=int, default=4)
    sd = sub.add_parser("dns", help="DNS-запрос")
    sd.add_argument("domains", nargs="+")
    st = sub.add_parser("tls", help="проверка TLS-сертификата")
    st.add_argument("domains", nargs="+")
    ss = sub.add_parser("sites", help="проверка блокировок")
    ss.add_argument("domains", nargs="*", help="свой список (по умолчанию — популярные)")
    sub.add_parser("report", help="полный отчёт")

    a = p.parse_args(argv)
    cmd = a.cmd or "report"
    out: dict = {}

    if cmd in ("ip", "report"):
        out["ip"] = public_ip()
    if cmd == "ping":
        with cf.ThreadPoolExecutor() as ex:
            out["ping"] = list(ex.map(lambda t: tcp_ping(*parse_target(t), count=a.count), a.targets))
    if cmd == "report":
        targets = ["1.1.1.1:443", "8.8.8.8:443", "google.com", "github.com"]
        with cf.ThreadPoolExecutor() as ex:
            out["ping"] = list(ex.map(lambda t: tcp_ping(*parse_target(t)), targets))
    if cmd == "dns":
        out["dns"] = [dns_lookup(d) for d in a.domains]
    if cmd == "tls":
        out["tls"] = [tls_info(d) for d in a.domains]
    if cmd in ("sites", "report"):
        domains = getattr(a, "domains", None) or DEFAULT_SITES
        out["sites"] = run_sites(domains)

    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0

    if "ip" in out:
        print_ip(out["ip"]); print()
    if "ping" in out:
        print(BOLD("TCP-задержка"))
        for r in out["ping"]:
            print_ping(r)
        print()
    if "dns" in out:
        print(BOLD("DNS"))
        for r in out["dns"]:
            print_dns(r)
    if "tls" in out:
        print(BOLD("TLS-сертификаты"))
        for r in out["tls"]:
            print_tls(r)
    if "sites" in out:
        print_sites(out["sites"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
