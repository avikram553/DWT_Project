from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from api.routes import regions, accidents, aggregates, zones, metadata

app = FastAPI(
    title="GeoCrash DE",
    description="Spatial Analysis of Traffic Accidents in Germany — TU Chemnitz DWT Project",
    version="0.1.0",
    license_info={"name": "dl-de/by-2-0", "url": "https://www.govdata.de/dl-de/by-2-0"},
    docs_url=None,
)

_FILL_QUESTION_DATA_JS = """
<button id="fill-question-data" style="position:fixed;top:10px;right:20px;z-index:9999;
padding:8px 14px;background:#49cc90;color:#fff;border:none;border-radius:4px;
font-weight:600;cursor:pointer;">Test with question data</button>
<script>
(function () {
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function setValue(input, value) {
    var proto = input.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype
      : input.tagName === "SELECT" ? window.HTMLSelectElement.prototype
      : window.HTMLInputElement.prototype;
    var setter = Object.getOwnPropertyDescriptor(proto, "value").set;
    setter.call(input, String(value));
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
  }

  async function fillQuestionData() {
    var spec = await fetch("./openapi.json").then(function (r) { return r.json(); });
    for (var path in spec.paths) {
      var methods = spec.paths[path];
      for (var method in methods) {
        var op = methods[method];
        if (!op.parameters) continue;
        var examples = {};
        op.parameters.forEach(function (p) {
          var schema = p.schema || {};
          var ex = (schema.examples && schema.examples[0] !== undefined) ? schema.examples[0] : schema.example;
          if (ex !== undefined) examples[p.name] = ex;
        });
        if (Object.keys(examples).length === 0) continue;

        var pathSpan = document.querySelector('.opblock-summary-path[data-path="' + CSS.escape(path) + '"]');
        if (!pathSpan) continue;
        var opblock = pathSpan.closest(".opblock");
        if (!opblock || !opblock.classList.contains("opblock-" + method)) continue;

        if (!opblock.classList.contains("is-open")) {
          opblock.querySelector(".opblock-summary").click();
          await sleep(150);
        }
        var tryBtn = opblock.querySelector(".try-out__btn");
        if (tryBtn && !tryBtn.classList.contains("cancel")) {
          tryBtn.click();
          await sleep(150);
        }
        for (var name in examples) {
          var row = opblock.querySelector('tr[data-param-name="' + CSS.escape(name) + '"]');
          if (!row) continue;
          var input = row.querySelector("input, select, textarea");
          if (!input) continue;
          setValue(input, examples[name]);
        }
      }
    }
  }

  document.getElementById("fill-question-data").addEventListener("click", fillQuestionData);
})();
</script>
"""

app.add_middleware(GZipMiddleware, minimum_size=1000)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000",
                   "http://localhost:3000", "http://127.0.0.1:3000",
                   "http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    html = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Swagger UI",
        swagger_js_url="/vendor/swagger-ui/swagger-ui-bundle.js",
        swagger_css_url="/vendor/swagger-ui/swagger-ui.css",
    ).body.decode()
    html = html.replace("</body>", _FILL_QUESTION_DATA_JS + "</body>")
    return HTMLResponse(html)


app.include_router(regions.router)
app.include_router(accidents.router)
app.include_router(aggregates.router)
app.include_router(zones.router)
app.include_router(metadata.router)

app.mount("/", StaticFiles(directory="/app/frontend", html=True), name="frontend")
