"""GLO-07: FastAPI sirve el frontend compilado (SPA) en el mismo origen."""

from httpx import ASGITransport, AsyncClient

from app.main import mount_frontend


async def make_client(tmp_path):
    from fastapi import FastAPI

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html>spa</html>")
    (tmp_path / "assets" / "app-abc123.js").write_text("console.log(1)")
    (tmp_path / "icon.png").write_bytes(b"png")
    (tmp_path.parent / "secret.txt").write_text("no")
    app = FastAPI()

    @app.get("/api/v1/ping")
    async def ping() -> dict[str, str]:
        return {"ok": "1"}

    mount_frontend(app, tmp_path)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_spa_fallback_and_static_files(tmp_path):
    async with await make_client(tmp_path) as c:
        assert (await c.get("/")).text == "<html>spa</html>"
        # Recargar una ruta de React Router devuelve index.html.
        assert (await c.get("/tarjetas")).text == "<html>spa</html>"
        assert (await c.get("/assets/app-abc123.js")).text == "console.log(1)"
        assert (await c.get("/icon.png")).content == b"png"


async def test_api_routes_win_and_unknown_api_is_404(tmp_path):
    async with await make_client(tmp_path) as c:
        assert (await c.get("/api/v1/ping")).json() == {"ok": "1"}
        assert (await c.get("/api/v1/nope")).status_code == 404


async def test_no_path_traversal_outside_dist(tmp_path):
    async with await make_client(tmp_path) as c:
        res = await c.get("/..%2Fsecret.txt")
        assert res.text != "no"
