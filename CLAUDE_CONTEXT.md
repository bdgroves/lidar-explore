# Claude pickup prompt

Paste the block below into a fresh Claude conversation on the other machine
after you've cloned and set up the repo. It gives Claude the context to jump
straight into the Snowflake integration.

---

I'm continuing a LiDAR forestry project. Everything is in the repo at
`git@github.com:bdgroves/lidar-explore.git` — please read `README.md` first
for full context.

**Where we are:**

- Windows + pixi environment, all deps installed via `pixi install`
- Working synthetic Finnish boreal forest sample (Nuuksio/Haukkalampi area,
  EPSG:3067, ~1M points, 450 known trees with species + heights as ground truth)
- CHM + DEM pipeline working (PDAL `filters.hag_nn`)
- Local-max tree detection working: 78.4% recall, 98.6% precision, F1 87.4%,
  height RMSE 0.44m — see README for full numbers
- Snowflake connector already added via pixi (`snowflake-connector-python`)
- I have Snowflake credentials on this machine

**What we want to do next:**

Load the detected trees (`data/nuuksio_detected_trees.csv`) into Snowflake as
`GEOGRAPHY` points and run some spatial queries. Rough plan:

1. Reproject from EPSG:3067 (TM35FIN) to EPSG:4326 (WGS84) — Snowflake
   `GEOGRAPHY` requires WGS84
2. Load to a staging table via `write_pandas`
3. Create a proper table with `TO_GEOGRAPHY(wkt)`
4. Run some interesting spatial queries — tree density per hex, nearest
   neighbors, filter by height, etc.
5. Bonus: pull it back and visualize via matplotlib

I'll tell you my Snowflake auth method (probably external browser / SSO) and
which database/schema to use. Please write a `load_to_snowflake.py` script
following the same clean style as the other scripts in the repo.

**Important:**

- Never write credentials into files. Use environment variables or an
  external-browser prompt.
- Add any Snowflake-specific ignore patterns (`.env`, `*.pem`, etc.) — the
  `.gitignore` already covers common ones.
- Keep the existing scripts working; add new ones rather than editing.
