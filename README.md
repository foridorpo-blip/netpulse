# NetPulse

Быстрая диагностика сети и VPN из терминала. Один файл, только стандартная библиотека Python — ставится за секунды и работает на Windows, Linux и macOS без прав администратора.

## Что умеет

| Команда | Что делает |
|---|---|
| `netpulse ip` | Публичный IP, страна, город, провайдер — сразу видно, работает ли VPN |
| `netpulse ping host[:port]` | TCP-пинг: задержка, jitter, потери (ICMP не нужен) |
| `netpulse dns domain` | A/AAAA-записи домена |
| `netpulse tls domain` | Версия TLS, издатель и срок действия сертификата |
| `netpulse sites [domains]` | Проверка доступности сервисов и этапа, на котором ломается соединение |
| `netpulse report` | Всё сразу (команда по умолчанию) |

Флаг `--json` выводит результат в JSON — удобно для скриптов, ботов и мониторинга.

## Установка

```bash
pip install git+https://github.com/foridorpo-blip/netpulse.git
```

Или без установки:

```bash
git clone https://github.com/foridorpo-blip/netpulse.git
cd netpulse
python -m netpulse
```

## Примеры

```bash
netpulse                              # полный отчёт
netpulse ip                           # проверить VPN
netpulse ping 1.1.1.1 github.com:22   # задержка до хостов
netpulse sites discord.com x.com      # открываются ли сайты
netpulse tls mysite.ru                # когда истекает сертификат
netpulse --json sites > status.json   # для автоматизации
```

Пример вывода `netpulse sites`:

```
Доступность сервисов
  ● google.com               54 мс
  ● github.com               61 мс
  ● discord.com            TLS   TLS сброшен (DPI?)
  ● x.com                  DNS   домен не резолвится
  Доступно 10 из 12
```

## Как читать статусы `sites`

| Статус | Что значит |
|---|---|
| `OK` | DNS, TCP и TLS прошли успешно |
| `DNS` | Домен не резолвится — блокировка на уровне DNS или нет интернета |
| `TCP` | IP найден, но соединение не устанавливается — блокировка по IP |
| `TLS` | Соединение сбрасывается при рукопожатии — типичный признак DPI/SNI-фильтрации |
| `CERT` | Сертификат не прошёл проверку — возможна подмена (MITM) |

## Требования

Python 3.9+. Внешних зависимостей нет.

## Лицензия

MIT
