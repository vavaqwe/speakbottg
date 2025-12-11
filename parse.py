from selenium import webdriver
from bs4 import BeautifulSoup
import json

driver = webdriver.Chrome()
driver.get("https://fichepizza.com.ua/korosten/")
html = driver.page_source
soup = BeautifulSoup(html, "html.parser")

products = []
for item in soup.select("div.item-product"):
    title = item.select_one("span.title-product").get_text(strip=True)
    desc = item.select_one("span.desc-product").get_text(strip=True)
    ingredients = [i.strip() for i in desc.split("/") if i.strip()]
    old_price_tag = item.select_one("span.price-text")
    old_price = old_price_tag.get_text(strip=True) if old_price_tag else ""

    products.append({
        "name": title,
        "ingredients": ingredients,
        "price": old_price.strip('від')
    })

with open("products.json", "w", encoding="utf-8") as f:
    json.dump(products, f, ensure_ascii=False, indent=2)

driver.quit()
