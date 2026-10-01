# AI Travel Planner

An actively developed, student-built travel planning app. A Streamlit questionnaire collects trip preferences, Groq proposes five destinations, and the selected destination becomes an editable itinerary built from places returned by Geoapify. The planner uses available OpenRouteService (ORS) routes and labels estimates or unavailable information rather than presenting them as verified facts.

## What it does

- Collects destination, style, duration, accommodation, transport, budget, and free-text preferences in a step-by-step questionnaire with a review screen.
- Uses Groq structured output for destination options and for interpreting natural-language intent and mobility preferences.
- Discovers actual accommodations, activities, and food places through Geoapify; ranks them against positive and negative preferences.
- Builds a day-by-day schedule with food options when discovered, free time, travel transitions, and constraint/plan-fit information. When suitable verified places and ORS routes exist, car or bicycle plans can include a regional two-stop day trip.
- Lets users replace a hotel, activity, lunch, or dinner; move or remove an activity; and build another itinerary. Candidate edits are validated before replacing the current plan.
- Shows an interactive map, Google Maps website links (no Google API key), factual selection explanations, budget/transport status, and a downloadable PDF of the current itinerary.

The app does **not** book travel or obtain live hotel, flight, train, bus, or restaurant prices. Budget totals include only available verified price records and clearly labelled fuel calculations; other costs remain unknown.

## How it is organized

```text
src/main.py                Streamlit entry point
src/app/ui/                Questionnaire, review, results, and itinerary map
src/app/ai/                Groq client, destination agent, intent/mobility analysis,
                           and real-place recommender
src/app/travel/            Geoapify discovery, place ranking, strategy, constraints,
                           scheduling, routing, budget, editing, and validation
src/app/reporting/         PDF report generated from the current validated plan
tests/                     Offline unit and integration tests
```

The main flow is: **questionnaire → Groq destination options → selected destination → Geoapify places → preference-aware itinerary → validation → editable results/map/PDF**. ORS supplies route distance and duration when a supported route is available; otherwise travel information is marked unavailable or used only as a labelled planning estimate.

## Technology and services

Python, Streamlit, `python-dotenv`, Requests, and ReportLab. The external integrations are [Groq](https://console.groq.com/docs/overview) for LLM requests, [Geoapify](https://apidocs.geoapify.com/) for geocoding and place discovery, and [OpenRouteService](https://openrouteservice.org/dev/#/api-docs) for supported walking, driving, and cycling routes. The map uses Leaflet/OpenStreetMap tiles; Google Maps links open its website without calling a Google API.

## Run locally

Use Python 3.11+ and create credentials for the services you intend to use. From the project root (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Set the following values in the local `.env` file (which is git-ignored):

```dotenv
GROQ_API_KEY=your_groq_api_key
GEOAPIFY_API_KEY=your_geoapify_api_key
ORS_API_KEY=your_openrouteservice_api_key
```

`GROQ_API_KEY` is needed for AI generation, and `GEOAPIFY_API_KEY` is needed for real-place plans. `ORS_API_KEY` enables verified supported routes; without it, route information is unavailable and routing-dependent planning is limited. `GROQ_MODEL` is an optional model override (see `.env.example`). Never commit real keys.

```powershell
python -m streamlit run src/main.py
```

Open the local URL shown by Streamlit, usually `http://localhost:8501`. Complete the questionnaire, generate destination options, and choose **View full plan** to build the detailed itinerary.

## Tests

The main suite uses offline sample/mocked provider data and does not require API keys:

```powershell
python -m unittest discover -s tests -v
```

Optional live smoke checks use your configured credentials and network access:

```powershell
python test_geoapify.py
python test_openrouteservice_live.py
```

## Known limitations / work in progress

- Place identity and categories come from Geoapify, but ratings, review counts, opening hours, amenities, availability, and most prices are not verified by the current integrations. They are not invented.
- ORS does not provide public-transport routes here. Motorcycle planning uses a labelled car-road proxy, not a verified motorcycle route. Regional days require usable place and route data.
- Activity durations and unrouted transition buffers may be conservative planning estimates. Map connector lines show stop order, not actual road geometry.
- The app depends on external API availability and quota. It is a planning prototype, not a booking or price-quotation service.
