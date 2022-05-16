from flask import Flask, request, jsonify, render_template
import requests
import json
from suntime import Sun
import datetime
import threading
import re
import math
import bs4
from selenium import webdriver
from selenium.webdriver.firefox.options import Options

global browser
options = Options()
options.headless = True
browser = webdriver.Firefox(options=options)
app = Flask(__name__)


class Estimate:
    def __init__(self, input_address):
        self.osm = self.geocoder(input_address)
        self.lat = float(self.osm["lat"])
        self.lon = float(self.osm["lon"])
        #t = threading.Thread(target=get_sunroof, args=(self.lat, self.lon))
        #t.start()
        self.fact, self.maxarea, self.usablesolar = get_sunroof(self.lat, self.lon)
        self.address = self.osm["display_name"]
        self.bbox = self.osm["boundingbox"]
        self.weather = self.get_forecast(self.lat, self.lon)
        self.pwrcost = self.get_pwr_cost(self.lat, self.lon)
        self.sun = Sun(self.lat, self.lon)



    def geocoder(self, address):
        url = "https://nominatim.openstreetmap.org/search.php?format=jsonv2&q={}".format(address)
        return requests.get(url).json()[0]

    def get_forecast(self, lat, long):
        query_url = "https://api.weather.gov/points/{},{}".format(lat, long)
        forecast_url = requests.get(query_url).json()["properties"]["forecastHourly"]
        forecast = requests.get(forecast_url, headers={"Feature-Flags": "forecast_wind_speed_qv"}).json()["properties"]["periods"]
        return forecast

    def get_daylight(self, tzday=datetime.datetime.today().date()):
        sunrise = self.sun.get_local_sunrise_time(tzday)
        sunset =  self.sun.get_local_sunset_time(tzday + datetime.timedelta(1)) # Need to add a day for sunset times for some reason
        daylight = sunset - sunrise
        return daylight

    def get_pwr_cost(self, lat, lon, KEY="BztmfU4zWoaozhRl6wRSaPy6ZdFMq56dChWLklPM"):
        url = "https://developer.nrel.gov/api/utility_rates/v3.json?api_key={}&lat={}&lon={}".format(KEY, lat, lon)
        return requests.get(url).json()["outputs"]["residential"]

    def calculate(self):
        # We just want 7 days...
        parsed = {}
        start = datetime.datetime.today().date()

        for i in range(7):
            key_date = start + datetime.timedelta(i)
            key = key_date.strftime('%Y-%m-%d')
            parsed[key] = {}
            daylight_delta = self.get_daylight(key_date) - datetime.timedelta(hours=1.5)
            parsed[key]["daylight"] = daylight_delta
            parsed[key]["wind"] = []

        for entry in self.weather:
            time = entry["endTime"].split("T")[0]
            if time in parsed:
                desc = entry["shortForecast"]

                if entry["isDaytime"] == True:
                    # https://forecast.weather.gov/glossary.php
                    if "Partly Sunny" in desc or "Partly Cloudy" in desc:
                        parsed[time]["daylight"] -= datetime.timedelta(hours=0.5)
                    elif "Mostly Cloudy" in desc:
                        parsed[time]["daylight"] -= datetime.timedelta(hours=0.8)
                    elif "Mostly Sunny" in desc:
                        parsed[time]["daylight"] -= datetime.timedelta(hours=0.2)
                    elif "cloudy" in desc or "Cloudy" in desc :
                        parsed[time]["daylight"] -= datetime.timedelta(hours=0.66)
                    elif "Showers" in desc:
                        parsed[time]["daylight"] -= datetime.timedelta(hours=0.95)

                # Append wind speed from km/h to m/s
                windspeed = (entry["windSpeed"]["value"])/(3.6)
                parsed[time]["wind"].append(round(windspeed, 3))

        for key in parsed:
            parsed[key]["date"] = key
            parsed[key]["avg_wind"] = round(sum(parsed[key]["wind"]) / len(  parsed[key]["wind"]),2)
            parsed[key]["totalkwh_wind"] = round((((2.62677157164 * ((1.2754 * math.pow(  parsed[key]["avg_wind"],3))/2.0)) * 2) * len(parsed[key]["wind"])) / 1000, 3) #Assuming 2, 6ft diameter turbine and dry air
            ##150 watts per square meter modern solar panels
            parsed[key]["totalkwh_solar"] = round(((self.usablesolar * 0.092903) * 150 * (parsed[key]["daylight"]/ datetime.timedelta(hours=1)))/1000,3)
            parsed[key]["daylight"] = round(parsed[key]["daylight"]/datetime.timedelta(hours=1),1)
        return {"lat": self.lat, "lon": self.lon, "address": self.address, "pwr": self.pwrcost, "fact": self.fact, "usable": self.usablesolar, "data": [*parsed.values()]}

def get_sunroof(lat, lon):
    url = "https://sunroof.withgoogle.com/building/{}/{}".format(lat, lon)
    browser.get(url)
    htmlsrc = browser.page_source
    soup = bs4.BeautifulSoup(htmlsrc, "html")
    text = soup.find_all("div", {"class": "panel-fact-text"})[-1].text.strip().replace("\n", "") + " (Project Sunroof)"
    text = re.sub(' +', ' ', text)
    sqft = int(text.split("sq")[0].replace(",", "").strip())
    usable = int(sqft * .75)
    return text, sqft, usable

options = Options()
options.headless = True


@app.route('/estimate')
def api_main():
    args = request.args
    address = args.get('address')
    impute = Estimate(address)
    calculated = impute.calculate()
    print(calculated)
    return render_template('estimate.html', pwr=calculated["pwr"],data=calculated["data"], address=calculated["address"], lat=calculated["lat"],lon=calculated["lon"],fact=calculated["fact"] )

@app.route('/')
def home():  # put application's code here
    return render_template('index.html')

if __name__ == '__main__':
    app.run()
