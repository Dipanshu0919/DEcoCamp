<div align="center">

<img src="https://api.iconify.design/lucide:handshake.svg?color=%234f46e5" width="64" height="64" />

# SahyogSutra

**A comprehensive community event management and collaboration platform.**

SahyogSutra brings people together by allowing users to create, discover, and participate in localized events, drives, and campaigns — powered by gamification, real-time communication, and AI.

<br/>

[![Live Demo](https://img.shields.io/badge/🌐%20Live%20Demo-sahyogsutra.run.place-4f46e5?style=for-the-badge)](https://sahyogsutra.run.place)

<br/>

### 🖥️ Live Preview

<a href="https://sahyogsutra.run.place">
  <img src="https://image.thum.io/get/maxAge/12/width/1280/http://sahyogsutra.run.place?preview=True" width="100%" alt="SahyogSutra Preview" />
</a>

</div>

---

## <img src="https://api.iconify.design/lucide:sparkles.svg?color=%23f59e0b" width="22" height="22" /> Key Features

<table>
  <tr>
    <td><img src="https://api.iconify.design/lucide:lock.svg?color=%23ef4444" width="20" height="20" /> <strong>Auth & Profiles</strong></td>
    <td>Secure email-based OTP verification for sign-ups and password resets. Users can manage profiles and track their organized events.</td>
  </tr>
  <tr>
    <td><img src="https://api.iconify.design/lucide:calendar.svg?color=%233b82f6" width="20" height="20" /> <strong>Event Management</strong></td>
    <td>Create, discover, and manage community events with an admin approval system to review, approve, or decline requests.</td>
  </tr>
  <tr>
    <td><img src="https://api.iconify.design/lucide:message-square.svg?color=%2310b981" width="20" height="20" /> <strong>Real-Time Group Chat</strong></td>
    <td>Dedicated live chat rooms for every event, powered by Socket.IO for instant collaboration.</td>
  </tr>
  <tr>
    <td><img src="https://api.iconify.design/lucide:bot.svg?color=%238b5cf6" width="20" height="20" /> <strong>AI Event Descriptions</strong></td>
    <td>Google Gemini GenAI auto-generates event descriptions in multiple tones — Formal, Informal, Promotional, and Entertaining.</td>
  </tr>
  <tr>
    <td><img src="https://api.iconify.design/lucide:globe.svg?color=%2306b6d4" width="20" height="20" /> <strong>Multilingual Support</strong></td>
    <td>Dynamic, live translation of platform content via Google Translate for a diverse user base.</td>
  </tr>
  <tr>
    <td><img src="https://api.iconify.design/lucide:trophy.svg?color=%23f59e0b" width="20" height="20" /> <strong>Leaderboard & Gamification</strong></td>
    <td>Real-time leaderboard tracking top 5 community organizers. Users can "like" events to push them into the Trending section.</td>
  </tr>
  <tr>
    <td><img src="https://api.iconify.design/lucide:download.svg?color=%2322c55e" width="20" height="20" /> <strong>Export & Sync</strong></td>
    <td>Export profile and event data to CSV, and download <code>.ics</code> calendar files to sync with personal calendars.</td>
  </tr>
  <tr>
    <td><img src="https://api.iconify.design/lucide:settings.svg?color=%236366f1" width="20" height="20" /> <strong>Advanced Admin Controls</strong></td>
    <td>Platform statistics, user management, and database connection pool monitoring to maintain server health.</td>
  </tr>
</table>

---

## <img src="https://api.iconify.design/lucide:layers.svg?color=%233b82f6" width="22" height="22" /> Tech Stack

**Backend & Architecture**

[![My Skills](https://skillicons.dev/icons?i=py,fastapi,sqlite)](https://skillicons.dev)

| | Technology |
|---|---|
| **Framework** | FastAPI (Python) |
| **Real-time Engine** | Python-SocketIO / ASGI |
| **Database** | SQLiteCloud (custom queue-based connection pool) |
| **AI & ML** | Google GenAI (Gemini) |
| **Translation** | Googletrans |

**Frontend**

[![My Skills](https://skillicons.dev/icons?i=html,css,js)](https://skillicons.dev)

| | Technology |
|---|---|
| **Templating** | Jinja2 |
| **Styling & Scripts** | Custom CSS/JS via FastAPI StaticFiles |

---

## <img src="https://api.iconify.design/lucide:folder-tree.svg?color=%23f59e0b" width="22" height="22" /> Project Structure
```
SahyogSutra/
├── app.py                 # Main FastAPI application, routing, and DB connection pool
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables
├── events.json            # Event categorization data
├── translations.json      # Dynamic cache for localized text strings
├── modules/               # Helper modules (email, event logic, utils)
├── templates/             # Jinja2 HTML templates (index, chat, profile, etc.)
└── static/                # CSS, JavaScript, images, and other static assets
```

---

## <img src="https://api.iconify.design/lucide:users.svg?color=%234f46e5" width="22" height="22" /> Contributing

Contributions, issues, and feature requests are welcome!

1. Fork the project
2. Create your feature branch — `git checkout -b feature/AmazingFeature`
3. Commit your changes — `git commit -m 'Add some AmazingFeature'`
4. Push to the branch — `git push origin feature/AmazingFeature`
5. Open a Pull Request

---

## <img src="https://api.iconify.design/lucide:file-text.svg?color=%236b7280" width="22" height="22" /> License

Distributed under the **MIT License**.
