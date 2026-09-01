# NodeFlow frontend

## Run locally

Start the API in a separate terminal from the repository root:

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

Then install and run the frontend:

```powershell
cd frontend
npm install
npm run dev
```

Vite proxies `/api` to `http://127.0.0.1:8000` in local development. Set
`VITE_NODEFLOW_API_URL` when deploying against another API host.

The UI uses the stable demo project ID seeded by the backend. It presents only
the endpoints currently implemented by the backend's project-intelligence API.
