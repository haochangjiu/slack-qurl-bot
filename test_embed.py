#!/usr/bin/env python3
"""
手动测试 google_maps_resolver.py 的完整流程（纯标准库，无外部依赖）
"""
from __future__ import annotations
import urllib.request
import urllib.parse
import re
from typing import Optional, Dict


def fetch_url(url: str, timeout: int = 30) -> tuple:
    """GET 请求，返回 (resolved_url, status_code, body)"""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        resolved_url = resp.geturl()
        body = resp.read().decode("utf-8", errors="replace")
        return resolved_url, resp.status, body


def extract_place_name(url: str) -> Optional[str]:
    m = re.search(r"/place/([^/@?]+)", url)
    if m:
        return urllib.parse.unquote(m.group(1))
    return None


def extract_directions_coords(url: str) -> Optional[Dict[str, str]]:
    """
    从 /dir/ URL 提取起点和终点坐标。

    URL 格式:
      /dir/lat1,lng1/lat2,lng2/@center_lat,lng,zoom/data=...
    返回 {"origin": "lat,lng", "destination": "lat,lng"} 或 None。
    """
    m = re.search(r"/dir/([^@]+)@", url)
    if not m:
        return None
    parts = m.group(1).split("/")
    if len(parts) < 2:
        return None
    origin = parts[0].rstrip("/")
    destination = parts[1].rstrip("/")
    return {"origin": origin, "destination": destination}


def test_resolver():
    short_url = "https://maps.app.goo.gl/jeX7baorENihb1Vi8"
    api_key = "AIzaSyDJ5L9jjd9pqmUYJg5wJC3oNSU_tT-9llo"

    # Step 1: 解析短链接
    print("=" * 60)
    print("STEP 1: 解析短链接 redirect chain")
    print("=" * 60)
    try:
        resolved_url, status, _ = fetch_url(short_url)
        print(f"  resolved_url: {resolved_url}")
        print(f"  status: {status}")
    except Exception as e:
        print(f"  FAIL: 解析失败: {e}")
        return

    # Step 2: 判断 URL 类型
    print("\n" + "=" * 60)
    print("STEP 2: 判断 URL 类型并构造 embed URL")
    print("=" * 60)
    embed_url = None
    if "/dir/" in resolved_url:
        print("  类型: /dir/ 导航链接")
        coords = extract_directions_coords(resolved_url)
        if coords:
            print(f"  origin: {coords['origin']}")
            print(f"  destination: {coords['destination']}")
            embed_url = (
                f"https://www.google.com/maps/embed/v1/directions"
                f"?key={api_key}"
                f"&origin={coords['origin']}"
                f"&destination={coords['destination']}"
            )
    else:
        place_name = extract_place_name(resolved_url)
        if place_name:
            print(f"  类型: /place/ 地点链接")
            print(f"  地点名称: {place_name}")
            embed_url = f"https://www.google.com/maps/embed/v1/place?key={api_key}&q={urllib.parse.quote(place_name)}"
        else:
            print("  FAIL: 无法识别的 URL 格式")
            return

    print(f"  构造 embed_url: {embed_url}")

    # Step 3: 提取 place_id（仅作参考）
    print("\n" + "=" * 60)
    print("STEP 3: 提取 place_id（data= 参数，仅作参考）")
    print("=" * 60)
    m = re.search(r"data=[^!]*(?:![^!]*){3}!(1s([^!]+))", resolved_url)
    if m:
        print(f"  place_id: {m.group(2)}")
    else:
        print("  (未匹配到 data= place_id)")

    # Step 4: 调用 Embed API
    print("\n" + "=" * 60)
    print("STEP 4: 调用 Maps Embed API")
    print("=" * 60)
    print(f"  请求 URL: {embed_url}")
    try:
        _, status2, body2 = fetch_url(embed_url, timeout=15)
        print(f"  Status: {status2}")
        print(f"  Body preview: {body2[:300]}")
        if status2 == 200 and body2:
            print("\n  OK: Embed API 调用成功！")
        else:
            print("\n  FAIL: Embed API 返回非 200 或空 body")
    except Exception as e:
        print(f"  FAIL: Embed API 调用失败: {e}")


if __name__ == "__main__":
    test_resolver()
