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
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"Config file not found at {CONFIG_PATH}")
    with open(CONFIG_PATH, 'r') as f:
        return json.load(f)

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

def analyze_forecast(data):
    hourly = data.get("hourly", {})
    times = hourly.get("time", [])
    gti = hourly.get("global_tilted_irradiance", [])
    temp = hourly.get("temperature_2m", [])
    cloud = hourly.get("cloud_cover", [])
    code = hourly.get("weather_code", [])
    
    # Group times by date to identify tomorrow
    dates = sorted(list(set(datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M").date() for t in times)))
    
    if len(dates) >= 2:
        tomorrow = dates[1]
    else:
        tomorrow = dates[0]
        
    print(f"Analyzing forecast for date: {tomorrow}")
    
    tomorrow_hours = []
    for t, g, tp, cl, cd in zip(times, gti, temp, cloud, code):
        dt = datetime.datetime.strptime(t, "%Y-%m-%dT%H:%M")
        if dt.date() == tomorrow:
            tomorrow_hours.append({
                "time": dt,
                "gti": float(g) if g is not None else 0.0,
                "temp": tp,
                "cloud": cl,
                "code": cd
            })
            
    if not tomorrow_hours:
        raise ValueError("No hourly forecast records found for tomorrow.")
        
    total_gti = sum(h["gti"] for h in tomorrow_hours)
    # Total energy is sum(hourly_gti) Wh/m2, convert to kWh/m2
    total_energy_kwh = total_gti / 1000.0
    
    peak_gti = max(h["gti"] for h in tomorrow_hours)
    
    # Filter daylight hours for calculating averages (6 AM to 8 PM)
    daylight_hours = [h for h in tomorrow_hours if 6 <= h["time"].hour <= 20]
    avg_temp = sum(h["temp"] for h in daylight_hours) / len(daylight_hours) if daylight_hours else 0.0
    avg_cloud = sum(h["cloud"] for h in daylight_hours) / len(daylight_hours) if daylight_hours else 0.0
    
    # Determine overall weather code (most frequent daylight code)
    if daylight_hours:
        codes = [h["code"] for h in daylight_hours]
        overall_code = max(set(codes), key=codes.count)
    else:
        overall_code = 0
        
    # Calculate optimal charging window
    # Defined as hours where GTI >= 50% of the peak value and peak_gti > 20 W/m2
    charging_hours = []
    threshold = 0.5 * peak_gti
    if peak_gti > 20.0:
        charging_hours = [h for h in tomorrow_hours if h["gti"] >= threshold]
        
    if charging_hours:
        start_hour = min(h["time"] for h in charging_hours)
        # End hour is the last hour + 1 to denote the full block
        end_hour = max(h["time"] for h in charging_hours) + datetime.timedelta(hours=1)
        window_str = f"{start_hour.strftime('%I:%M %p')} - {end_hour.strftime('%I:%M %p')}"
        duration = len(charging_hours)
    else:
        window_str = "No suitable window"
        duration = 0
        
    # Rate the day's solar potential
    if total_energy_kwh >= 5.0:
        rating = "Excellent"
        rating_color = "#10b981" # Emerald Green
    elif total_energy_kwh >= 3.0:
        rating = "Good"
        rating_color = "#3b82f6" # Blue
    elif total_energy_kwh >= 1.5:
        rating = "Moderate"
        rating_color = "#f59e0b" # Amber
    else:
        rating = "Poor"
        rating_color = "#ef4444" # Red
        
    return {
        "date": tomorrow,
        "total_energy": total_energy_kwh,
        "peak_gti": peak_gti,
        "avg_temp": avg_temp,
        "avg_cloud": avg_cloud,
        "weather_code": overall_code,
        "window": window_str,
        "duration": duration,
        "rating": rating,
        "rating_color": rating_color,
        "hourly_data": tomorrow_hours
    }

def format_text_email(report):
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
            
    text += f"\nLocation: 9 Foster Drive, Dartford DA1 5UB, UK\nPanels: South-West facing (Tilt: 35°, Azimuth: 45°)\nGenerated at {datetime.datetime.now().strftime('%Y-%m-%d %I:%M %p')}\n"
    return text

def format_html_email(report):
    weather_desc, weather_emoji = get_weather_desc(report["weather_code"])
    
    # Format rows for hourly breakdown
    hourly_rows = ""
    for h in report["hourly_data"]:
        hour = h["time"].hour
        if 6 <= hour <= 20:
            time_str = h["time"].strftime("%I:%M %p")
            percentage = (h["gti"] / report["peak_gti"] * 100) if report["peak_gti"] > 0 else 0
            
            # Apply color based on irradiance strength
            if h["gti"] >= 400:
                bar_color = "linear-gradient(90deg, #f59e0b 0%, #eab308 100%)" # bright solar gold
            elif h["gti"] >= 150:
                bar_color = "linear-gradient(90deg, #3b82f6 0%, #60a5fa 100%)" # mild daylight blue
            else:
                bar_color = "linear-gradient(90deg, #475569 0%, #64748b 100%)" # low intensity grey-blue
                
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
            
    # HTML string
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
            
            <!-- Hourly Forecast Table -->
            <h3 style="font-size: 15px; font-weight: 700; color: #f8fafc; text-transform: uppercase; letter-spacing: 0.05em; border-bottom: 1px solid #1e293b; padding-bottom: 8px; margin: 0 0 16px 0;">Hourly Forecast (06:00 - 20:00)</h3>
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
            <p style="margin: 0; font-size: 10px; color: #475569;">Generated automatically by Solar Optimizer Agent at {datetime.datetime.now().strftime('%I:%M %p %Z')}</p>
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
    
    # Check if we should dry run
    dry_run = "--dry-run" in sys.argv
    
    if not sender or not password or not server_addr or dry_run:
        print("Running in Dry Run / Local Saving mode.")
        html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_email.html")
        txt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_email.txt")
        
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(text_content)
            
        print(f"Saved email copy to:\n  HTML: {html_file}\n  Text: {txt_file}")
        if dry_run:
            print("Reason: --dry-run flag was set.")
        else:
            print("Reason: SMTP configuration in config.json is incomplete.")
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
        # Save locally as fallback
        html_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_email.html")
        txt_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "last_email.txt")
        with open(html_file, "w", encoding="utf-8") as f:
            f.write(html_content)
        with open(txt_file, "w", encoding="utf-8") as f:
            f.write(text_content)
        print(f"Saved email copy locally to {html_file} due to transmission failure.")
        return False

def main():
    try:
        config = load_config()
        lat = config["latitude"]
        lon = config["longitude"]
        tilt = config["tilt"]
        azimuth = config["azimuth"]
        
        raw_data = fetch_forecast(lat, lon, tilt, azimuth)
        report = analyze_forecast(raw_data)
        
        subject = f"Solar Charging Advisory: {report['rating']} potential tomorrow ({report['date'].strftime('%b %d')})"
        text_content = format_text_email(report)
        html_content = format_html_email(report)
        
        send_email(config, subject, html_content, text_content)
        print("Forecast compilation complete.")
    except Exception as e:
        print(f"Fatal execution error: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
