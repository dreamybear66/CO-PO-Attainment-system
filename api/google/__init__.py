"""Google sign-in and the Google Forms API (phase 8), over plain HTTPS with httpx.

Each teacher connects their own Google account once (OAuth, offline access); forms are created in
that teacher's Drive. Only the refresh token is stored, encrypted. Free Google APIs only: Forms API
and OAuth. No Google client library is needed.
"""
