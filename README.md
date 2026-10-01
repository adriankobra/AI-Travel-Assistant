# AI Travel Planner

A beginner-friendly Streamlit MVP for collecting travel preferences through a guided, visual questionnaire. The app is deliberately built in phases: the current version completes the questionnaire and review experience, while later phases will add Groq-powered planning, estimated budgets, itineraries, and PDF export.

## Current features

- Welcome screen and ten-step travel questionnaire
- Back/forward navigation with answers retained in Streamlit session state
- Predefined choices with optional custom input where useful
- Progress indicator and a review screen before AI generation
- Country data isolated in the UI module so it can later move to a data file or API

## Structure

```
src/
  main.py                 # Streamlit entry point and app styling
  app/ui/questionnaire.py # Questions, state handling, and navigation
  app/ui/review.py        # Review screen
```

## Groq connection (Phase 2)

`app/ai/groq_client.py` is the single reusable integration point for Groq. It loads the key from the project-level `.env` file, offers plain-text and JSON-object requests, and turns common configuration/request/empty-response problems into friendly errors.

Copy `.env.example` to `.env`, then replace the placeholder:

```env
GROQ_API_KEY=your_groq_api_key_here
```

On the welcome screen, expand **Developer: test Groq connection** and select **Test Groq connection**. It sends one small JSON request and displays the result.

## AI travel recommendations (Phase 3)

`app/ai/travel_agent.py` passes the saved questionnaire answers to Groq together with a travel-planner system prompt. Groq is required to return exactly five options in a strict JSON schema. The TravelAgent then verifies the expected fields and checks that every option includes every itinerary day in order, with at least three activities per day.

The results screen labels all costs as **estimates**. It does not query hotels, flights, maps, weather, or any other real-time travel source.

## Phase 4.1: intent and place ranking

Before the real-place itinerary request, `app/ai/intent_analyzer.py` asks Groq to convert the questionnaire choices and optional note into structured positive or negative concepts with a strength. It does not ask Groq to discover places or make factual claims.

`app/travel/place_ranking.py` then ranks only the actual Geoapify place categories. Strong positive verified matches rise; strong negative verified matches are penalized. A concept that has no matching provider category remains an explicit unverified concept rather than becoming an invented service or facility.

## Phase 4.3: expanded real-place discovery

`app/travel/category_config.py` is the single configuration point for Geoapify Places API categories. The activity search now requests these verified category groups: attractions and culture; wellness and water; bicycle, car and boat rental; parks, protected nature and outdoor places; restaurants and cafés; bars and pubs; family activities; and shopping.

Each result remains a factual `Place` record. Alongside its name, address, coordinates, ID and Geoapify categories, the record keeps city, country and datasource metadata when Geoapify supplies them. Results are deduplicated by Geoapify place ID (falling back to name and coordinates), while merged category metadata is retained for ranking.

The general-purpose intent analyzer is unchanged. Ranking compares its concepts only with categories that Geoapify actually returned. A request such as `jet ski rental` is retained as user intent but explicitly unverified when no returned category matches; the planner does not invent a provider.

## Phase 4.4: place quality and explainable ranking

The current Geoapify Places integration provides factual identity and location data: name, address, categories, coordinates, place ID, city/country, and datasource metadata when supplied. It does **not** provide ratings, review counts, or popularity fields, so the current quality and popularity score components are zero rather than guessed. Geoapify documents its Places response fields and category-based search, but does not list review or rating signals in that response. [Geoapify Places API documentation](https://apidocs.geoapify.com/docs/places/)

`app/travel/place_quality.py` is an extension point for a future named external quality source. It accepts an optional verified `quality` record only when it includes its source, and keeps rating (quality), review volume/popularity, and data confidence separate.

Final ranking is deterministic:

`final_score = preference_score + category_relevance_score + quality_score + popularity_score + data_confidence_score`

Strong negative preferences are an ordering guard: a place matching a strong dislike is ranked after non-conflicting places, regardless of quality/popularity evidence. Recommendation reasons use only returned Geoapify category matches and, if present in a future provider response, explicitly named verified quality evidence.

## Phase 4.5: mobility and route-aware preparation

`app/travel/mobility.py` defines a `MobilityProfile` that keeps capability (`driving_license`), availability (`own_car`, rental permissions), and preference (`preferred_transport`, walking/public-transport/bicycle/motorcycle strength) separate. Unknown values stay `null`. It can also represent mixed city/outside-city strategies without forcing a single mode.

`app/ai/mobility_analyzer.py` complements the existing general intent analyzer by extracting this profile from the same questionnaire notes using strict structured output. Mobility does not replace travel intent: a spa preference and a walking-only constraint remain independent inputs to ranking and validation.

`app/travel/routing.py` is provider-neutral. Its current `UnavailableRoutingService` returns no distance or duration and labels the result `unavailable`; the existing conservative transition buffer remains an explicit estimate. No route time is fabricated. When Geoapify supplies a place distance, walking-only profiles favour nearby candidates and the validator rejects a selected place beyond the documented local walking policy threshold. Car-rental places are rejected when rental is explicitly disallowed.

## Phase 4.7: verified OpenRouteService routing

`app/travel/routing_openrouteservice.py` is the only OpenRouteService-specific layer. It uses the current ORS endpoint `https://api.heigit.org/openrouteservice/v2/directions`, never the deprecated `api.openrouteservice.org` endpoint. It supports `walking`, `driving`/the existing `car` profile alias, and `bicycle`; public transport and unsupported modes are explicitly unavailable.

Add this local-only value to `.env` (it is already present as a placeholder in `.env.example`):

```env
ORS_API_KEY=your_openrouteservice_api_key_here
```

For a successful provider response, the adapter returns verified `distance_meters` and `duration_minutes` through the existing `RouteEstimate` contract with `source: openrouteservice`. `DailyPlanner` uses that verified duration for a selected itinerary transition. If a key, coordinates, network request, response, or rate limit is unavailable, the route is labelled unavailable and the existing conservative transition buffer stays an explicit estimate instead. No fallback time is described as verified route data.

The provider keeps an in-memory cache keyed by origin coordinates, destination coordinates, and transport mode, so repeated requests in a plan do not make duplicate ORS calls. Routing runs only for selected itinerary transitions, not for every discovered Geoapify candidate. Route geometry is not displayed yet.

The normal test suite is offline. If `ORS_API_KEY` is configured, an optional safe live smoke test can be run separately:

```powershell
.\.venv\Scripts\python.exe test_openrouteservice_live.py
```

Run the application from the project folder:

```powershell
.\.venv\Scripts\python.exe -m streamlit run src/main.py
```

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run src/main.py
```

## Final itinerary, food, maps and PDF reports

The detailed plan remains compatible with the existing `activities` list, and
also adds an ordered `items` timeline to every day. Timeline items use the
explicit types `accommodation`, `activity`, `meal`, `travel`, and `free_time`.
Relevant entries preserve real-place name, address, coordinates, Geoapify place
ID/categories, scheduled times, and data source.

`DailyPlanner` adds a route transition before every selected activity, including
the first transition from the selected accommodation when its coordinates are
available. A successful ORS response provides verified distance and duration.
If a route cannot be obtained, the timeline says `unavailable` and uses only a
separate, clearly labelled planning buffer; it never presents that buffer as an
ORS result. Activity durations and meal allowances follow the same explicit
`verified` / `estimated` / `unavailable` distinction.

Food discovery is a separate Geoapify query using only the configured
restaurant, cafe, food-court, and marketplace categories. The planner
offers up to three factual choices for lunch and dinner near the day's first or
last activity. It does not infer cuisine from a business name. Each choice has
an ORS route summary only when ORS actually returned one.

`app/travel/map_links.py` creates coordinate-first Google Maps *website* links
for individual places, individual transitions, and complete days. This uses no
Google API or API key. Long or incomplete multi-stop routes fall back to the
individual location links. The results page also renders a small Leaflet map
with OpenStreetMap tiles, ordered markers, and a dashed ordering line. The line
is not described as route geometry because ORS geometry is not currently kept.

`app/reporting/pdf_report.py` renders the existing validated itinerary with
ReportLab. It does not ask Groq for another plan. It includes the overview,
chronological day timelines, verified versus estimated status, food choices,
route/location links, and day summaries. PDF export re-runs
`TravelPlanValidator`; an invalid itinerary cannot be exported.

No paid APIs were added. The app continues to use Geoapify for real places and
OpenRouteService for supported walking, car/driving, and bicycle routes.
Public transport remains unavailable rather than estimated.

## Regional day trips

For car, motorcycle, or bicycle trips, the planner can use a wider Geoapify
discovery set to form a two-stop regional day while retaining a local day.
Both stops must be real returned places, and the outward, between-stop, and
return legs must have ORS distance and duration. The day-trip explanation,
budget fuel calculation, map stop order, and PDF are refreshed from the current
validated itinerary after edits. Motorcycle routing is explicitly labelled as
a **car-road proxy**: ORS does not verify motorcycle travel time.

Walking-only and public-transport plans remain local when a farther trip cannot
be verified. ORS does not provide public-transport routing, so the app does not
claim a verified transit day trip. If provider routing is unavailable, regional
promotion is skipped and the existing valid plan is kept. The dashed map lines
show ordered stops, not road geometry.
