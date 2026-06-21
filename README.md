# AI-Crawler 🚀

An intelligent, AI-driven web crawler powered by a high-performance **FastAPI (Python)** backend and a responsive **React (Tailwind CSS)** user interface. The entire stack is optimized to run locally via Docker with automated multi-stage builds.

---

## 🏗️ System Architecture

This project is configured as a unified service for easy local deployment:
* **`frontend-builder`**: A temporary Node.js container that installs UI dependencies and generates static optimized production builds.
* **`app`**: The primary FastAPI backend container that hosts the REST API endpoints and actively serves the compiled frontend static files.
* **`redis`**: An Alpine-based Redis caching and task queue layer to handle crawling states asynchronously.

---

## ⚡ Getting Started

The easiest way to clone and launch this entire application on your localhost is by using **Docker Compose**.

### Prerequisites
Ensure you have the following installed on your machine:
* [Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker Engine
* [Docker Compose](https://docs.docker.com/compose/install/)

---

### 🚀 Setup & Execution Instructions

1. **Clone the Repository**
   ```
   git clone https://github.com/Southker/AI-Crawler.git
   cd AI-Crawler
   ```

2. **Spin Up the Containers**
   Run the following command in your terminal to initialize the automated build and start the ecosystem:
   ```
   sudo docker compose up --build
   ```
> ⚠️ **Note:** Scanning results and depth may vary significantly depending on the target website's configuration. Security protections (like Cloudflare or Web Application Firewalls) and modern Single Page Application (SPA) architectures (like React or Next.js) may restrict or alter path discovery compared to traditional websites. I am still working onto improving the tool more efficient and accurate. 
