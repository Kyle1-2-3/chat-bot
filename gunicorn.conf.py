# One request can make two 15-second Gemini calls. Keep worker lifetime above
# that bound, with time for local work and sending the final stream frame.
timeout = 45
