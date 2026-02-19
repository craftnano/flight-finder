# Production TODO

## Before Launch
- [ ] Upgrade to Amadeus Production API keys (test env has limited data and rate limits)
- [ ] Set up custom domain (makemefly.app)
- [ ] Upgrade to Python 3.10+ to get Pillow 12.1.1 (fixes GHSA-cfh3-3jmp-rvhc — low risk on 3.9 since only a known SVG logo is loaded)

## Infrastructure
- [ ] Move rate limiting (API usage + IP limits) from JSON files to a database for multi-worker support
- [ ] Add proper logging (structured, no PII)
- [ ] Set up error monitoring (Sentry or similar)
- [ ] Configure Streamlit secrets management for production credentials

## Nice to Have
- [ ] Add round-trip vs one-way toggle
- [ ] Multi-city search
- [ ] Price alerts / email notifications
- [ ] Historical price charts
- [ ] Mobile-optimized layout
