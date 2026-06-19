import os
import json
import urllib.request
import urllib.parse
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import ssl
import sys

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

def load_config():
    config = {}
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to parse config.json ({e}). Using defaults.", file=sys.stderr)
            
    # Override with Environment Variables if available (useful for GitHub Actions)
    config["latitude"] = float(os.environ.get("SOLAR_LATITUDE", config.get("latitude", 51.458)))
    config["longitude"] = float(os.environ.get("SOLAR_LONGITUDE", config.get("longitude", 0.208)))
    config["tilt"] = float(os.environ.get("SOLAR_TILT", config.get("tilt", 35)))
    config["azimuth"] = float(os.environ.get("SOLAR_AZIMUTH", config.get("azimuth", 45)))
    config["recipient_email"] = os.environ.get("SOLAR_RECIPIENT_EMAIL", config.get("recipient_email", "sambathknair@gmail.com"))
    
    # Load Octopus Tariff Code from config or environment
    config["octopus_tariff_code"] = os.environ.get("OCTOPUS_TARIFF_CODE", config.get("octopus_tariff_code", "E-1R-AGILE-24-10-01-C"))
    
    if "whatsapp" not in config:
        config["whatsapp"] = {}
    config["whatsapp"]["phone"] = os.environ.get("WHATSAPP_PHONE", config["whatsapp"].get("phone", "+447823372929"))
    config["whatsapp"]["apikey"] = os.environ.get("WHATSAPP_APIKEY", config["whatsapp"].get("apikey", ""))
    
    if "smtp" not in config:
        config["smtp"] = {}
    config["smtp"]["server"] = os.environ.get("SMTP_SERVER", config["smtp"].get("server", "smtp.gmail.com"))
    config["smtp"]["port"] = int(os.environ.get("SMTP_PORT", config["smtp"].get("port", 587)))
    config["smtp"]["use_tls"] = os.environ.get("SMTP_USE_TLS", str(config["smtp"].get("use_tls", True))).lower() == "true"
    config["smtp"]["sender_email"] = os.environ.get("SENDER_EMAIL", config["smtp"].get("sender_email", ""))
    config["smtp"]["sender_password"] = os.environ.get("SENDER_PASSWORD", config["smtp"].get("sender_password", ""))
    
    # Determine the notification channel
    # Prioritizes explicit env variable first, then config.json.
    # Fallback: Auto-config based on populated secrets
    channel_env = os.environ.get("SOLAR_CHANNEL")
    if channel_env:
        config["channel"] = channel_env.lower()
    elif "channel" in config:
        config["channel"] = config["channel"].lower()
    else:
        # Auto-detect channels based on available configuration/credentials
        has_whatsapp = bool(config["whatsapp"]["phone"] and config["whatsapp"]["apikey"])
        has_smtp = bool(config["smtp"]["sender_email"] and config["smtp"]["sender_password"])
        if has_whatsapp and has_smtp:
            config["channel"] = "both"
        elif has_smtp:
            config["channel"] = "email"
        else:
            config["channel"] = "whatsapp"
            
    return config

def get_weather_desc(code):
    wmo_codes = {
        0: ("Clear Sky", "☀️"),
        1: ("Mainly Clear", "🌤️"),
        2: ("Partly Cloudy", "⛅"),
        3: ("Overcast", "☁️"),
        45: ("Fog", "🌫️"),
        48: ("Depositing Rime Fog", "🌫️"),
        51: ("Light Drizzle", "🌦️"),
        53: ("Moderate Drizzle", "🌦️"),
        55: ("Dense Drizzle", "🌦️"),
        56: ("Light Freezing Drizzle", "❄️"),
        57: ("Dense Freezing Drizzle", "❄️"),
        61: ("Slight Rain", "🌧️"),
        63: ("Moderate Rain", "🌧️"),
        65: ("Heavy Rain", "🌧️"),
        66: ("Light Freezing Rain", "❄️"),
        67: ("Heavy Freezing Rain", "❄️"),
        71: ("Slight Snowfall", "🌨️"),
        73: ("Moderate Snowfall", "🌨️"),
        75: ("Heavy Snowfall", "🌨️"),
        77: ("Snow Grains", "🌨️"),
        80: ("Slight Rain Showers", "🌧️"),
        81: ("Moderate Rain Showers", "🌧️"),
        82: ("Violent Rain Showers", "🌧️"),
        85: ("Slight Snow Showers", "🌨️"),
        86: ("Heavy Snow Showers", "🌨️"),
        95: ("Thunderstorm", "🌩️"),
        96: ("Thunderstorm with Slight Hail", "🌩️"),
        99: ("Thunderstorm with Heavy Hail", "🌩️")
    }
    return wmo_codes.get(code, ("Unknown", "❓"))

def get_london_time():
    # Pure Python timezone helper to compute London local time (handling GMT/BST transitions)
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    year = now_utc.year
    
    # BST starts on the last Sunday of March at 1:00 AM UTC (2:00 AM BST)
    march_31 = datetime.datetime(year, 3, 31, 1, 0, tzinfo=datetime.timezone.utc)
    bst_start = march_31 - datetime.timedelta(days=(march_31.weekday() + 1) % 7)
    
    # BST ends on the last Sunday of October at 1:00 AM UTC (2:00 AM BST)
    october_31 = datetime.datetime(year, 10, 31, 1, 0, tzinfo=datetime.timezone.utc)
    bst_end = october_31 - datetime.timedelta(days=(october_31.weekday() + 1) % 7)
    
    if bst_start <= now_utc < bst_end:
        return now_utc + datetime.timedelta(hours=1)
    else:
        return now_utc

def fetch_forecast(lat, lon, tilt, azimuth):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "global_tilted_irradiance,temperature_2m,cloud_cover,weather_code",
        "tilt": tilt,
        "azimuth": azimuth,
        "timezone": "Europe/London",
        "forecast_days": 2
    }
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"
    
    print(f"Fetching solar forecast from Open-Meteo: {full_url}")
    req = urllib.request.Request(full_url, headers={'User-Agent': 'Mozilla/5.0'})
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode())

def analyze_forecast(data, target_date):
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    gti = hourly.get("global_tilted_irradiance", [])
    temp = hourly.get("temperature_2m", [])
    cloud = hourly.get("cloud_cover", [])
    code = hourly.get("weather_code", [])
    
    print(f"Filtering and analyzing solar forecast for date: {target_date}")
    
    target_hours = []
    for t, g, tp, cl, cd in zip(times, gti, temp, cloud, code):
        dt = datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M")
        if dt.date() == target_date:
            target_hours.append({
                "time": dt,
                "gti": float(g) if g is not None else 0.0,
                "temp": tp,
                "cloud": cl,
                "code": cd
            })
            
    # Fallback to the first available date in data if target_date is not in data
    if not target_hours:
        dates_available = sorted(list(set(datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M").date() for t in times)))
        if dates_available:
            fallback_date = dates_available[0]
            print(f"Warning: Target date {target_date} not in solar forecast. Falling back to: {fallback_date}")
            target_date = fallback_date
            for t, g, tp, cl, cd in zip(times, gti, temp, cloud, code):
                dt = datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M")
                if dt.date() == fallback_date:
                    target_hours.append({
                        "time": dt,
                        "gti": float(g) if g is not None else 0.0,
                        "temp": tp,
                        "cloud": cl,
                        "code": cd
                    })
        else:
            raise ValueError("No hourly forecast records found in API response.")
        
    total_gti = sum(h["gti"] for h in target_hours)
    total_energy_kwh = total_gti / 1000.0
    peak_gti = max(h["gti"] for h in target_hours)
    
    daylight_hours = [h for h in target_hours if 6 <= h["time"].hour <= 20]
    avg_temp = sum(h["temp"] for h in daylight_hours) / len(daylight_hours) if daylight_hours else 0.0
    avg_cloud = sum(h["cloud"] for h in daylight_hours) / len(daylight_hours) if daylight_hours else 0.0
    
    if daylight_hours:
        codes = [h["code"] for h in daylight_hours]
        overall_code = max(set(codes), key=codes.count)
    else:
        overall_code = 0
        
    charging_hours = []
    threshold = 0.5 * peak_gti
    if peak_gti > 20.0:
        charging_hours = [h for h in target_hours if h["gti"] >= threshold]
        
    if charging_hours:
        start_hour = min(h["time"] for h in charging_hours)
        end_hour = max(h["time"] for h in charging_hours) + datetime.timedelta(hours=1)
        window_str = f"{start_hour.strftime('%I:%M %p')} - {end_hour.strftime('%I:%M %p')}"
        duration = len(charging_hours)
    else:
        window_str = "No suitable window"
        duration = 0
        
    if total_energy_kwh >= 5.0:
        rating = "Excellent"
        rating_color = "#10b981"
    elif total_energy_kwh >= 3.0:
        rating = "Good"
        rating_color = "#3b82f6"
    elif total_energy_kwh >= 1.5:
        rating = "Moderate"
        rating_color = "#f59e0b"
    else:
        rating = "Poor"
        rating_color = "#ef4444"
        
    return {
        "date": target_date,
        "total_energy": total_energy_kwh,
        "peak_gti": peak_gti,
        "avg_temp": avg_temp,
        "avg_cloud": avg_cloud,
        "weather_code": overall_code,
        "window": window_str,
        "duration": duration,
        "rating": rating,
        "rating_color": rating_color,
        "hourly_data": target_hours
    }

def fetch_octopus_rates(config, target_date):
    # Retrieve dynamic tariff and extract product code
    tariff_code = config.get("octopus_tariff_code", "E-1R-AGILE-24-10-01-C")
    product_code = "AGILE-24-10-01"
    
    if tariff_code.startswith("E-1R-"):
        parts = tariff_code[5:].split("-")
        if len(parts) >= 4:
            product_code = "-".join(parts[:-1])
            
    url = f"https://api.octopus.energy/v1/products/{product_code}/electricity-tariffs/{tariff_code}/standard-unit-rates/"
    
    # Determine BST offset for target_date: BST (+1h) runs last Sun Mar → last Sun Oct
    year = target_date.year
    bst_start = (datetime.datetime(year, 3, 31, 1, 0, tzinfo=datetime.timezone.utc)
                 - datetime.timedelta(days=(datetime.datetime(year, 3, 31).weekday() + 1) % 7)).date()
    bst_end   = (datetime.datetime(year, 10, 31, 1, 0, tzinfo=datetime.timezone.utc)
                 - datetime.timedelta(days=(datetime.datetime(year, 10, 31).weekday() + 1) % 7)).date()
    utc_offset_hours = 1 if bst_start <= target_date < bst_end else 0

    # Octopus rates are always UTC; query the UTC window that covers the full London day
    from_dt = datetime.datetime(target_date.year, target_date.month, target_date.day,
                                0, 0, 0) - datetime.timedelta(hours=utc_offset_hours)
    to_dt   = datetime.datetime(target_date.year, target_date.month, target_date.day,
                                23, 59, 59) - datetime.timedelta(hours=utc_offset_hours)
    from_str = from_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    to_str   = to_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    
    params = {
        "period_from": from_str,
        "period_to": to_str
    }
    query_string = urllib.parse.urlencode(params)
    full_url = f"{url}?{query_string}"
    
    print(f"Fetching Agile Octopus rates from: {full_url}")
    req = urllib.request.Request(full_url, headers={'User-Agent': 'Mozilla/5.0'})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode())
            results = data.get("results", [])
            if not results:
                print("No rates found in the requested date range. Fetching latest rates page as fallback...")
                req_fallback = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_fallback, timeout=15) as resp_fallback:
                    data_fallback = json.loads(resp_fallback.read().decode())
                    results = data_fallback.get("results", [])
            return results
    except Exception as e:
        print(f"Error fetching Octopus rates: {e}", file=sys.stderr)
        return []

def utc_to_london(dt_utc):
    """Convert a naive UTC datetime to a naive London local datetime (GMT or BST)."""
    dt_aware = dt_utc.replace(tzinfo=datetime.timezone.utc)
    year = dt_aware.year
    bst_start = (datetime.datetime(year, 3, 31, 1, 0, tzinfo=datetime.timezone.utc)
                 - datetime.timedelta(days=(datetime.datetime(year, 3, 31).weekday() + 1) % 7))
    bst_end   = (datetime.datetime(year, 10, 31, 1, 0, tzinfo=datetime.timezone.utc)
                 - datetime.timedelta(days=(datetime.datetime(year, 10, 31).weekday() + 1) % 7))
    offset = datetime.timedelta(hours=1) if bst_start <= dt_aware < bst_end else datetime.timedelta(0)
    return (dt_aware + offset).replace(tzinfo=None)

def parse_octopus_time(valid_from_str):
    """Parse an Octopus valid_from string (always UTC) and return London local time."""
    try:
        dt_utc = datetime.datetime.strptime(valid_from_str, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        dt_utc = datetime.datetime.strptime(valid_from_str[:19], "%Y-%m-%dT%H:%M:%S")
    return utc_to_london(dt_utc)

def process_octopus_rates(results, target_date):
    day_rates = []
    for r in results:
        local_time = parse_octopus_time(r["valid_from"])
        if local_time.date() == target_date:
            day_rates.append({
                "time": local_time,
                "value": float(r["value_inc_vat"])
            })

    # Fallback to the most frequent London-local date if target_date has no records
    if not day_rates and results:
        dates_in_results = [parse_octopus_time(r["valid_from"]).date() for r in results]

        if dates_in_results:
            fallback_date = max(set(dates_in_results), key=dates_in_results.count)
            print(f"Tariff target date {target_date} not available. Using fallback date: {fallback_date}")
            target_date = fallback_date
            for r in results:
                local_time = parse_octopus_time(r["valid_from"])
                if local_time.date() == fallback_date:
                    day_rates.append({
                        "time": local_time,
                        "value": float(r["value_inc_vat"])
                    })
                    
    if not day_rates:
        return {
            "date": target_date,
            "by_price": [],
            "by_time": []
        }
        
    # Sort by price ascending to extract top 6
    cheapest = sorted(day_rates, key=lambda x: x["value"])
    top_6 = cheapest[:6]
    
    # Sort configurations:
    # 1. Sorted by price ascending (cheapest first)
    top_6_by_price = sorted(top_6, key=lambda x: x["value"])
    # 2. Sorted by time ascending (chronological flow)
    top_6_by_time = sorted(top_6, key=lambda x: x["time"])
    
    return {
        "date": target_date,
        "by_price": top_6_by_price,
        "by_time": top_6_by_time
    }

def format_whatsapp_message(report, octopus_report):
    weather_desc, weather_emoji = get_weather_desc(report["weather_code"])
    
    msg = f"☀️ *Solar Charging Advisor* ⚡\n"
    msg += f"Date: {report['date'].strftime('%A, %b %d, %Y')}\n"
    msg += f"Rating: *{report['rating']}* ({weather_emoji} {weather_desc})\n\n"
    
    msg += f"🔋 *Optimal Solar Charging*:\n"
    msg += f"👉 *{report['window']}* 👈\n"
    msg += f"({report['duration']} hour(s) of high-yield solar)\n\n"
    
    msg += f"📊 *Solar Metrics*:\n"
    msg += f"• Est. Energy: {report['total_energy']:.2f} kWh/m²\n"
    msg += f"• Peak Intensity: {report['peak_gti']:.0f} W/m²\n"
    msg += f"• Avg Temperature: {report['avg_temp']:.1f}°C\n"
    msg += f"• Avg Cloud Cover: {report['avg_cloud']:.0f}%\n\n"
    
    if octopus_report and octopus_report["by_price"]:
        msg += f"💰 *Agile Octopus Rates* ({octopus_report['date'].strftime('%b %d')}):\n"
        msg += f"*(Top 6 Cheapest - Sorted Ascending)*\n"
        msg += "```"
        msg += "Time      Price (inc VAT)\n"
        msg += "-------------------------\n"
        for r in octopus_report["by_price"]:
            time_str = r["time"].strftime("%I:%M %p")
            val_str = f"{r['value']:.2f} p/kWh"
            msg += f"{time_str:<9} {val_str:<15}\n"
        msg += "```\n"
        
        msg += f"📅 *Top 6 Chronological Flow*:\n"
        msg += "```"
        msg += "Time      Price (inc VAT)\n"
        msg += "-------------------------\n"
        for r in octopus_report["by_time"]:
            time_str = r["time"].strftime("%I:%M %p")
            val_str = f"{r['value']:.2f} p/kWh"
            msg += f"{time_str:<9} {val_str:<15}\n"
        msg += "```\n"
        
    msg += f"📅 *Hourly Solar Forecast*:\n"
    msg += "```"
    msg += "Time      Irrad.    Cloud\n"
    msg += "-------------------------\n"
    for h in report["hourly_data"]:
        hour = h["time"].hour
        if 6 <= hour <= 20:
            time_str = h["time"].strftime("%I:%M %p")
            gti_str = f"{h['gti']:.0f} W/m²"
            cloud_str = f"{h['cloud']}%"
            msg += f"{time_str:<9} {gti_str:<10} {cloud_str:>4}\n"
    msg += "```"
    
    msg += f"\nDartford DA1 5UB, UK (SW facing)"
    return msg

def format_text_email(report, octopus_report):
    weather_desc, weather_emoji = get_weather_desc(report["weather_code"])
    
    text = f"""Solar Charging Forecast - {report['date'].strftime('%A, %b %d, %Y')}
======================================================

Tomorrow's Solar Rating: {report['rating']} ({weather_emoji} {weather_desc})

Optimal Battery Charging Window:
  >>>  {report['window']}  <<<
  (Duration: {report['duration']} hour(s) of high-yield solar)

Key Forecast Metrics:
---------------------
* Estimated Solar Energy: {report['total_energy']:.2f} kWh/m²
* Peak Solar Intensity: {report['peak_gti']:.0f} W/m²
* Daylight Avg Temp: {report['avg_temp']:.1f}°C
* Daylight Avg Cloud Cover: {report['avg_cloud']:.0f}%
"""

    if octopus_report and octopus_report["by_price"]:
        text += f"\nAgile Octopus Rates ({octopus_report['date'].strftime('%b %d')}):\n"
        text += "---------------------\n"
        text += "Top 6 Cheapest timeslots (sorted ascending):\n"
        for r in octopus_report["by_price"]:
            text += f"* {r['time'].strftime('%I:%M %p')} : {r['value']:.2f} p/kWh\n"

    text += """
Hourly Breakdown (06:00 - 20:00):
----------------------------------
"""
    for h in report["hourly_data"]:
        hour = h["time"].hour
        if 6 <= hour <= 20:
            time_str = h["time"].strftime("%I:%M %p")
            bar_len = int(h["gti"] / report["peak_gti"] * 20) if report["peak_gti"] > 0 else 0
            bar = "#" * bar_len + "-" * (20 - bar_len)
            text += f"{time_str:<8} | {h['gti']:>4.0f} W/m² | [{bar}] | {h['temp']:>4.1f}°C | {h['cloud']:>3d}% Cloud\n"
            
    london_now = get_london_time()
    tz_label = "BST" if london_now.utcoffset() and london_now.utcoffset().seconds == 3600 else "GMT"
    text += f"\nLocation: 9 Foster Drive, Dartford DA1 5UB, UK\nPanels: South-West facing (Tilt: 35°, Azimuth: 45°)\nGenerated at {london_now.strftime('%Y-%m-%d %I:%M %p')} {tz_label}\n"
    return text

def format_html_email(report, octopus_report):
    weather_desc, weather_emoji = get_weather_desc(report["weather_code"])
    london_now = get_london_time()
    tz_label = "BST" if london_now.utcoffset() and london_now.utcoffset().seconds == 3600 else "GMT"
    
    hourly_rows = ""
    for h in report["hourly_data"]:
        hour = h["time"].hour
        if 6 <= hour <= 20:
            time_str = h["time"].strftime("%I:%M %p")
            percentage = (h["gti"] / report["peak_gti"] * 100) if report["peak_gti"] > 0 else 0
            
            if h["gti"] >= 400:
                bar_color = "linear-gradient(90deg, #f59e0b 0%, #eab308 100%)"
            elif h["gti"] >= 150:
                bar_color = "linear-gradient(90deg, #3b82f6 0%, #60a5fa 100%)"
            else:
                bar_color = "linear-gradient(90deg, #475569 0%, #64748b 100%)"
                
            hourly_rows += f"""
            <tr style="border-bottom: 1px solid #1e293b;">
                <td style="padding: 12px 8px; color: #94a3b8; font-weight: 500; font-size: 14px;">{time_str}</td>
                <td style="padding: 12px 8px; color: #f8fafc; font-weight: 600; font-size: 14px; text-align: right;">{h['gti']:.0f} <span style="font-size: 10px; color: #64748b;">W/m²</span></td>
                <td style="padding: 12px 16px; width: 45%;">
                    <div style="background-color: #1e293b; border-radius: 4px; height: 10px; width: 100%; overflow: hidden;">
                        <div style="background: {bar_color}; height: 100%; width: {percentage}%; border-radius: 4px;"></div>
                    </div>
                </td>
                <td style="padding: 12px 8px; color: #cbd5e1; font-size: 14px; text-align: right;">{h['temp']:.1f}°C</td>
                <td style="padding: 12px 8px; color: #cbd5e1; font-size: 14px; text-align: right;">{h['cloud']}%</td>
            </tr>
            """
            
    octopus_section = ""
    if octopus_report and octopus_report["by_price"]:
        octopus_rows = ""
        for r in octopus_report["by_price"]:
            time_str = r["time"].strftime("%I:%M %p")
            val_str = f"{r['value']:.2f} p/kWh"
            
            is_cheapest = r == octopus_report["by_price"][0]
            bg_style = 'background-color: #eab30811; font-weight: 700;' if is_cheapest else ''
            accent_style = 'color: #fbbf24;' if is_cheapest else 'color: #f8fafc;'
            badge = '<span style="background-color: #fbbf24; color: #000; font-size: 9px; font-weight: 800; padding: 2px 6px; border-radius: 10px; margin-left: 8px;">CHEAPEST</span>' if is_cheapest else ''
            
            octopus_rows += f"""
            <tr style="border-bottom: 1px solid #1e293b; {bg_style}">
                <td style="padding: 12px 8px; color: #94a3b8; font-size: 14px;">{time_str} {badge}</td>
                <td style="padding: 12px 8px; {accent_style} font-size: 14px; text-align: right;">{val_str}</td>
            </tr>
            """
            
        octopus_section = f"""
        <!-- Agile Octopus Tariff -->
        <h3 style="font-size: 15px; font-weight: 700; color: #f8fafc; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #1e293b; padding-bottom: 8px; margin: 30px 0 16px 0;">💰 Agile Octopus Tariff ({octopus_report['date'].strftime('%A, %b %d')})</h3>
        <p style="font-size: 13px; color: #94a3b8; margin-top: 0; margin-bottom: 12px;">Top 6 cheapest half-hourly timeslots (sorted by price ascending):</p>
        <div style="background-color: #0f172a; border-radius: 10px; border: 1px solid #1e293b; overflow: hidden; margin-bottom: 30px;">
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="border-bottom: 2px solid #1e293b; text-align: left; background-color: #0b0f19;">
                        <th style="padding: 10px 8px; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase;">Timeslot</th>
                        <th style="padding: 10px 8px; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase; text-align: right;">Price (inc. VAT)</th>
                    </tr>
                </thead>
                <tbody>
                    {octopus_rows}
                </tbody>
            </table>
        </div>
        """
        
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
    <title>Solar Charge Forecast</title>
</head>
<body style="background-color: #0b0f19; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 20px; -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; color: #f8fafc;">
    <div style="max-width: 600px; margin: 0 auto; background-color: #0f172a; border-radius: 16px; overflow: hidden; border: 1px solid #1e293b; box-shadow: 0 10px 25px -5px rgba(0,0,0,0.3);">
        
        <!-- Header Banner -->
        <div style="background: linear-gradient(135deg, #1e3a8a 0%, #0f172a 100%); padding: 30px; text-align: center; border-bottom: 1px solid #1e293b; position: relative;">
            <div style="font-size: 12px; font-weight: 700; color: #60a5fa; letter-spacing: 0.15em; text-transform: uppercase; margin-bottom: 6px;">Solar Panel Optimization</div>
            <h1 style="font-size: 26px; font-weight: 800; color: #f8fafc; margin: 0; letter-spacing: -0.025em;">Solar Charging Advisor</h1>
            <p style="color: #94a3b8; font-size: 14px; margin: 8px 0 0 0;">Forecast for {report['date'].strftime('%A, %B %d, %Y')}</p>
        </div>
        
        <!-- Main Dashboard -->
        <div style="padding: 30px;">
            
            <!-- Overall Rating -->
            <div style="display: flex; align-items: center; justify-content: space-between; background-color: #1e293b; border-radius: 12px; padding: 16px 20px; margin-bottom: 24px; border: 1px solid #334155;">
                <div>
                    <span style="font-size: 14px; color: #94a3b8; display: block; font-weight: 500;">Outlook tomorrow</span>
                    <span style="font-size: 18px; font-weight: 700; color: #f8fafc;">{weather_emoji} {weather_desc}</span>
                </div>
                <div style="background-color: {report['rating_color']}; color: #ffffff; font-weight: 800; font-size: 14px; padding: 6px 16px; border-radius: 20px; text-transform: uppercase; letter-spacing: 0.05em; box-shadow: 0 4px 10px rgba(0,0,0,0.15);">
                    {report['rating']} Day
                </div>
            </div>
            
            <!-- Window Advice Card -->
            <div style="background: linear-gradient(145deg, #151e33 0%, #0c1220 100%); border-radius: 16px; padding: 24px; text-align: center; border: 1px solid #233253; margin-bottom: 28px; box-shadow: 0 10px 20px -5px rgba(0, 0, 0, 0.4);">
                <div style="display: inline-block; background-color: #eab30822; padding: 10px; border-radius: 50%; margin-bottom: 12px;">
                    <span style="font-size: 28px; line-height: 1;">⚡</span>
                </div>
                <h2 style="font-size: 14px; font-weight: 600; color: #cbd5e1; text-transform: uppercase; letter-spacing: 0.1em; margin: 0 0 8px 0;">Best Time Window to Charge</h2>
                <div style="font-size: 32px; font-weight: 800; color: #fbbf24; text-shadow: 0 0 15px rgba(251,191,36,0.3); margin-bottom: 6px;">{report['window']}</div>
                <p style="font-size: 14px; color: #94a3b8; margin: 0;">Recommended duration: <b>{report['duration']} hour(s)</b> based on SW irradiance</p>
            </div>
            
            <!-- Performance Statistics Grid -->
            <h3 style="font-size: 15px; font-weight: 700; color: #f8fafc; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #1e293b; padding-bottom: 8px; margin: 0 0 16px 0;">Solar Energy Details</h3>
            <table style="width: 100%; border-collapse: collapse; margin-bottom: 30px;">
                <tr>
                    <td style="width: 50%; padding: 0 10px 16px 0;">
                        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 14px; border-radius: 10px; text-align: center;">
                            <span style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; display: block; margin-bottom: 4px;">Energy Output</span>
                            <span style="font-size: 20px; font-weight: 700; color: #3b82f6;">{report['total_energy']:.2f} <span style="font-size: 12px;">kWh/m²</span></span>
                        </div>
                    </td>
                    <td style="width: 50%; padding: 0 0 16px 10px;">
                        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 14px; border-radius: 10px; text-align: center;">
                            <span style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; display: block; margin-bottom: 4px;">Peak Intensity</span>
                            <span style="font-size: 20px; font-weight: 700; color: #fbbf24;">{report['peak_gti']:.0f} <span style="font-size: 12px;">W/m²</span></span>
                        </div>
                    </td>
                </tr>
                <tr>
                    <td style="width: 50%; padding: 0 10px 0 0;">
                        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 14px; border-radius: 10px; text-align: center;">
                            <span style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; display: block; margin-bottom: 4px;">Avg Temp</span>
                            <span style="font-size: 20px; font-weight: 700; color: #cbd5e1;">{report['avg_temp']:.1f}°C</span>
                        </div>
                    </td>
                    <td style="width: 50%; padding: 0 0 0 10px;">
                        <div style="background-color: #0f172a; border: 1px solid #1e293b; padding: 14px; border-radius: 10px; text-align: center;">
                            <span style="font-size: 11px; color: #64748b; font-weight: 600; text-transform: uppercase; display: block; margin-bottom: 4px;">Avg Cloud Cover</span>
                            <span style="font-size: 20px; font-weight: 700; color: #cbd5e1;">{report['avg_cloud']:.0f}%</span>
                        </div>
                    </td>
                </tr>
            </table>
            
            {octopus_section}
            
            <!-- Hourly Forecast Table -->
            <h3 style="font-size: 15px; font-weight: 700; color: #f8fafc; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #1e293b; padding-bottom: 8px; margin: 0 0 16px 0;">Hourly Solar Forecast (06:00 - 20:00)</h3>
            <div style="overflow-x: auto;">
                <table style="width: 100%; border-collapse: collapse;">
                    <thead>
                        <tr style="border-bottom: 2px solid #1e293b; text-align: left;">
                            <th style="padding: 8px; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase;">Time</th>
                            <th style="padding: 8px; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase; text-align: right;">Irradiance</th>
                            <th style="padding: 8px 16px; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase; width: 45%;">Relative Strength</th>
                            <th style="padding: 8px; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase; text-align: right;">Temp</th>
                            <th style="padding: 8px; color: #64748b; font-size: 11px; font-weight: 700; text-transform: uppercase; text-align: right;">Cloud</th>
                        </tr>
                    </thead>
                    <tbody>
                        {hourly_rows}
                    </tbody>
                </table>
            </div>
            
        </div>
        
        <!-- Footer -->
        <div style="background-color: #0b0f19; padding: 20px 30px; border-top: 1px solid #1e293b; text-align: center; font-size: 12px; color: #64748b;">
            <p style="margin: 0 0 6px 0;"><b>Location:</b> 9 Foster Drive, Dartford DA1 5UB, UK</p>
            <p style="margin: 0 0 12px 0;"><b>Panel Configuration:</b> South-West facing | Tilt: 35° | Azimuth: 45°</p>
            <p style="margin: 0; font-size: 10px; color: #475569;">Generated automatically by Solar Optimizer Agent at {london_now.strftime('%I:%M %p')} {tz_label}</p>
        </div>
    </div>
</body>
</html>
"""
    return html

def send_email(config, subject, html_content, text_content):
    recipient = config["recipient_email"]
    smtp_conf = config.get("smtp", {})
    
    sender = smtp_conf.get("sender_email")
    password = smtp_conf.get("sender_password")
    server_addr = smtp_conf.get("server")
    port = smtp_conf.get("port", 587)
    use_tls = smtp_conf.get("use_tls", True)
    
    dry_run = "--dry-run" in sys.argv
    
    if not sender or not password or not server_addr or dry_run:
        print("Running in Email Dry Run / Local Saving mode.")
        html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_email.html")
        txt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_email.txt")
        
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(text_content)
            
        print(f"Saved email copy to:\n  HTML: {html_file}\n  Text: {txt_file}")
        return False
        
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = recipient
    
    part1 = MIMEText(text_content, 'plain')
    part2 = MIMEText(html_content, 'html')
    msg.attach(part1)
    msg.attach(part2)
    
    context = ssl.create_default_context()
    try:
        print(f"Connecting to SMTP server {server_addr}:{port}...")
        if use_tls:
            server = smtplib.SMTP(server_addr, port, timeout=15)
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
        else:
            server = smtplib.SMTP_SSL(server_addr, port, context=context, timeout=15)
            
        print(f"Logging in as {sender}...")
        server.login(sender, password)
        print(f"Sending email to {recipient}...")
        server.sendmail(sender, recipient, msg.as_string())
        server.quit()
        print("Email successfully sent!")
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_email.html")
        txt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_email.txt")
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(text_content)
        print(f"Saved email copy locally to {html_file} due to transmission failure.")
        return False

def send_whatsapp(config, message):
    wa_conf = config.get("whatsapp", {})
    phone = wa_conf.get("phone", "")
    apikey = wa_conf.get("apikey", "")
    
    dry_run = "--dry-run" in sys.argv
    
    if not phone or not apikey or dry_run:
        print("Running in WhatsApp Dry Run / Local Saving mode.")
        txt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_whatsapp.txt")
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(message)
        print(f"Saved WhatsApp message to:\n  Text: {txt_file}")
        
        if not apikey:
            print("\n--- ACTION REQUIRED: ACTIVATE WHATSAPP NOTIFICATIONS ---")
            print("To send WhatsApp messages directly to your phone, get a free CallMeBot API key:")
            print("1. Add the CallMeBot number to your phone contacts: +34 644 97 53 59 (or +34 644 10 55 37)")
            print("2. Send this exact message to it via WhatsApp: I allow callmebot to send me messages")
            print("3. Wait for the reply message containing your APIKEY.")
            print("4. Copy that APIKEY into the 'apikey' field in config.json.")
            print("---------------------------------------------------------\n")
        return False
        
    params = urllib.parse.urlencode({
        "phone": phone,
        "text": message,
        "apikey": apikey
    })
    url = f"https://api.callmebot.com/whatsapp.php?{params}"
    
    try:
        print(f"Sending WhatsApp message to {phone}...")
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as response:
            resp_content = response.read().decode('utf-8')
            print("CallMeBot Server Response:", resp_content)
            print("WhatsApp message successfully sent!")
            return True
    except Exception as e:
        print(f"Error sending WhatsApp message: {e}", file=sys.stderr)
        txt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_whatsapp.txt")
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(message)
        print(f"Saved message locally to {txt_file} as a fallback.")
        return False

def main():
    try:
        config = load_config()
        lat = config["latitude"]
        lon = config["longitude"]
        tilt = config["tilt"]
        azimuth = config["azimuth"]
        channel = config.get("channel", "whatsapp").lower()
        
        # Determine target date: today if before 5 PM (17:00) London time, tomorrow if at/after
        london_now = get_london_time()
        if london_now.hour < 17:
            target_date = london_now.date()
            print(f"Current local time in London is {london_now.strftime('%I:%M %p')}. Running in BEFORE 5 PM mode. Target date is TODAY ({target_date}).")
        else:
            target_date = london_now.date() + datetime.timedelta(days=1)
            print(f"Current local time in London is {london_now.strftime('%I:%M %p')}. Running in AFTER 5 PM mode. Target date is TOMORROW ({target_date}).")
            
        # 1. Fetch data
        raw_solar_data = fetch_forecast(lat, lon, tilt, azimuth)
        raw_octopus_rates = fetch_octopus_rates(config, target_date)
        
        # 2. Process data
        solar_report = analyze_forecast(raw_solar_data, target_date)
        octopus_report = process_octopus_rates(raw_octopus_rates, solar_report["date"])
        
        # 3. Format and Route
        if channel in ("whatsapp", "both"):
            whatsapp_msg = format_whatsapp_message(solar_report, octopus_report)
            send_whatsapp(config, whatsapp_msg)
            
        if channel in ("email", "both"):
            subject = f"Solar Charging Advisory: {solar_report['rating']} potential ({solar_report['date'].strftime('%b %d')})"
            text_content = format_text_email(solar_report, octopus_report)
            html_content = format_html_email(solar_report, octopus_report)
            send_email(config, subject, html_content, text_content)
            
        print("Forecast compilation complete.")
    except Exception as e:
        print(f"Fatal execution error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
