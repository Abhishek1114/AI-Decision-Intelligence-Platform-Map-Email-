# phase2/webhooks/usgs_webhook.py

from fastapi import FastAPI, Request, HTTPException
from phase2.ingestion.sources.usgs import normalise_usgs
from phase2.ingestion.normaliser import EventNormaliser

app = FastAPI(title="Supply Chain Event Webhook Receiver")

normaliser = EventNormaliser()


@app.post("/webhooks/usgs")
async def receive_usgs_webhook(request: Request):
    """
    USGS sends GeoJSON FeatureCollection to this endpoint on new earthquakes.
    Registered at: https://earthquake.usgs.gov/ens/
    (USGS Earthquake Notification Service)
    """
    payload = await request.json()

    features = payload.get("features", [])
    if not features:
        # USGS sometimes sends a test ping with empty features
        return {"status": "ok", "message": "no features in payload"}

    ingested = 0
    for feature in features:
        mag = feature.get("properties", {}).get("mag", 0)
        if mag < 5.0:
            continue   # Below threshold — ignore
        raw = normalise_usgs(feature)
        result = normaliser.process(source="usgs", raw_dict=raw)
        if result:
            ingested += 1

    return {"status": "ok", "ingested": ingested}


@app.get("/health")
async def health():
    return {"status": "ok"}