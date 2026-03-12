import json
import re
from urllib.parse import quote
from bs4 import BeautifulSoup
import pywikibot
from concurrent.futures import ThreadPoolExecutor, as_completed
from pywikibot import pagegenerators
import requests

# 调用 Wikipedia Search API，返回相关页面标题列表
# 目的：获得初始的扩展种类，之后进行主题的自适应搜索
def search_related_pages(search_query):
    # 对查询词进行URL编码，处理特殊字符和空格
    encoded_query = quote(search_query)
    
    # 构建API请求URL（注意：将 cmlimit=max 更改为 srlimit=50）
    url = f"https://en.wikipedia.org/w/api.php?action=query&list=search&srsearch={encoded_query}&format=json&srlimit=50"
    
    # 添加请求头，模拟浏览器访问，避免被某些服务器拒绝[citation:10]
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    #Making the request
    response = requests.get(url, headers=headers)

    # Checking if request was successful
    if response.status_code == 200:
        data = response.json()
        search_results = data['query']['search']

        # Extracting titles of the search results
        related_pages = [result['title'] for result in search_results]
        return related_pages
    else:
        print("Failed to retrieve data from Wikipedia API.")
        return []



"""获取单个页面的入链数（用于多线程）"""
def get_backlinks_for_page(page_title):
    site = pywikibot.Site('en', 'wikipedia')
    page = pywikibot.Page(site, page_title)
    
    try:
        backlinks = page.backlinks(namespaces=[0])
        count = sum(1 for _ in backlinks)
        print(f"{page_title}: {count}个入链")
        return (page_title, count)
    except Exception as e:
        print(f"获取{page_title}时出错: {e}")
        return (page_title, 0)

# 批量获取页面的入链数：可用于泛化性的重要性比较
def batch_get_backlinks(page_titles, max_workers=3):
    """
    批量获取多个页面的入链数
    
    参数:
        page_titles: 页面标题列表
        site_code: 维基语言代码
        max_workers: 最大线程数
    """
    results = {}
    
    # 使用线程池并行处理
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(get_backlinks_for_page, task): task for task in page_titles}
        
        for future in as_completed(futures):
            title, count = future.result()
            results[title] = count
    
    return results




# 查询某个Wikipedia页面在时间段内的访问量总和
def get_pageviews(page_title, start_date="2020121500", end_date="2025121500"):
    access_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJSUzI1NiJ9.eyJhdWQiOiIwMDFkMTFmNmQ2MzVmMGY4YmI3MDlkNWViN2ZhNDRlYiIsImp0aSI6IjMzOGQ0Mzc0YzNmZjE5NjBlZDkzNjIwNTdiYjMwYjExOWYzZTY2MzVkZjM3NmY3NDcyZjczMDcyMjNiYzU4ODFjODBkOTliOTZmMjAzZGNkIiwiaWF0IjoxNzEyNjEwMTg0LjY4OTIyNywibmJmIjoxNzEyNjEwMTg0LjY4OTIzLCJleHAiOjMzMjY5NTE4OTg0LjY4NzY1Mywic3ViIjoiNzUzODczODIiLCJpc3MiOiJodHRwczovL21ldGEud2lraW1lZGlhLm9yZyIsInJhdGVsaW1pdCI6eyJyZXF1ZXN0c19wZXJfdW5pdCI6NTAwMCwidW5pdCI6IkhPVVIifSwic2NvcGVzIjpbImJhc2ljIl19.YN0ZvSzsBuYe3Mg-r0C63cWxDXPU3GOCyspUqg4mMv27Qw1FJq9F9H6JKJAUMrqQxB-xyWZqpu8mekvMoxb3Ha5S2fpPbuM4gMB0JketqG2obaDd4QqgtJjg8KDYKwR8ieKoPRLDSHv3Tv4NcvIL-EvzjkRybqrukzQwttwuBUwxmlY8vhC1BZed7URt_-KhMYPsnNfJLSBeWivYJOmrqF2S04AOS0Egjul8Pz_yXAQ7q7aqpIwg6X2jod0ZN5h1gnmAvZmoLB7mKSAxrHEUL2zaQ8BVERWostWVA9ek556cuUJe5NusQ0XW7pcsYIi0YpFjKOBuq-tXzuOlbxFhlbwrp6xkhE_grQGNs1IxyT-w_sjQc2gI48FDe0ldDrTg6ZmgLELsjJM8xOxBy1ng1fY73p-QnaDdxX4hqRw2ZBDlZ1E2j84lvVrv62x_SHPiBNAeywEPcOqDRV_XbU6ArOyJ7QTZXRu9UOT0XDQ-Fx3maCRGb35W4aOtLSWL-SSXYLI8ZuOQ2BwKQQYYbEDMp0W7NjHWzh8YPv6Y2wDaMzsAqaxk2c36pNvTToiTc_P6_a56lydQwoT8ACx1kzzw5lTNPKPEPxPGNiMgtsL3VqtxJWMR7Lgq-ZKwI7cwQ5FTp2YriQDBYuvoaDQeG_eVh8BlNlyg26OYojtYbNos3os"
    # client_id = "001d11f6d635f0f8bb709d5eb7fa44eb"
    # client_secret = "630b434daa4c8f6cce03b1c294b59574c1ce9431"  # Example client secret
    headers = {
        'Authorization': f'Bearer {access_token}',
        'User-Agent': 'wikipagerank',
    }

    # Construct the API URL with the appropriate parameters
    url = f"https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article/en.wikipedia/all-access/all-agents/{page_title}/daily/{start_date}/{end_date}"
    # Make the HTTP GET request to the API
    response = requests.get(url, headers=headers)
    # Check if the request was successful
    if response.status_code == 200:
        # Parse the JSON response
        data = response.json()
        # Extract the pageview data
        print('retrieved for ', page_title)
        views = sum(item['views'] for item in data['items'])
        return views
    else:
        print(f"Failed to retrieve pageviews data for {page_title}. Status code: {response.status_code}")
        return 0

# 修正编码问题，防止乱码
def clean_str(p):
  try:
    return p.encode().decode("unicode-escape").encode("latin1").decode("utf-8")
  except:
    return ''



# 按行拆分，去掉空行，返回段落列表
def get_page_obs(page):
    # find all paragraphs
    pattern = r'\[\d+\]'
    page =  re.sub(pattern, '', page)
    paragraphs = page.split("\n")
    paragraphs = [p.strip() for p in paragraphs if p.strip()]
    return paragraphs

# 基于页面访问量进行重要性重排的函数
# 只保留最常被访问的类别
def saliency_rerank(json_lst, num_keep = 5 ):
    for line_ in json_lst:
        page_title = line_['category'].replace(' ', '_')
        pageviews = get_pageviews(page_title)
        line_['salience'] = pageviews  if pageviews is not None else 0 # add the pageviews to the line.
    # sort by the saliency
    json_lst = sorted(json_lst, key=lambda x: x['salience'], reverse=True)
    for line in json_lst:
        print(f'salience of {line["category"]}: ', round(line['salience'] / 1000000, 2),  'M')
    return json_lst[:num_keep]



# 获取维基百科中与查询相似的匹配列表，现在代码中会自动调用
def get_wikipedia_similar_matches(query, limit=10):
    """
    获取维基百科中与查询相似的匹配列表
    
    Args:
        query: 查询词
        limit: 返回结果数量
        lang: 语言代码（默认英文）
    
    Returns:
        list: 相似匹配的标题列表
    """
    base_url = f"https://en.wikipedia.org/w/api.php"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    params = {
        "action": "opensearch",
        "search": query,
        "limit": limit,
        "format": "json",
        "namespace": 0  # 只搜索主命名空间
    }
    
    try:
        response = requests.get(base_url,headers=headers,params=params)
        response.raise_for_status()
        data = response.json()
        
        # opensearch返回格式: [query, [titles], [descriptions], [urls]]
        if len(data) >= 2:
            return data[1]  # 返回标题列表
        return []
    
    except requests.exceptions.RequestException as e:
        print(f"请求错误: {e}")
        return []
    except json.JSONDecodeError as e:
        print(f"JSON解析错误: {e}")
        return []



# 通过维基百科智能搜索实体
# 获得主题的相关文章
def search_step(entity,min_token=20,output_more=False):
    entity_ = entity.replace(" ", "+")
    search_url = f"https://en.wikipedia.org/w/index.php?search={entity_}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    response = requests.get(search_url, headers=headers)
    response_text = response.text
    soup = BeautifulSoup(response_text, features="html.parser")
    print(response.url)
    result_divs = soup.find_all("div", {"class": "mw-search-result-heading"})
    if result_divs:  # mismatch,无精确匹配，返回搜索列表
        result_titles = [clean_str(div.get_text().strip()) for div in result_divs]
        # obs = f"Could not find {entity}. Similar: {result_titles[:5]}."
        print(f"Could not find {entity}. Search for similar entities, {result_titles[0]}, instead")
        obs, entity = search_step(result_titles[0],min_token,output_more) # 递归搜索第一个相似结果
    else:
        print('found entity', entity)

        # ====== 新增：定义参考文献相关关键词 ======
        stop_titles = {
            "references", "notes", "bibliography",
            "external links", "see also"
        }

        page_ = ""
        content_div = soup.find('div', id='bodyContent') or soup.find('div', class_='mw-parser-output')
        content_soup = content_div if content_div else soup

        # 顺序遍历正文结构
        for tag in content_soup.find_all(["h2","h3", "p", "ul"]):

            # ====== 遇到参考文献标题则停止 ======
            if tag.name == "h2":
                headline = tag.get_text().strip()
                if any(t in headline.lower() for t in stop_titles):
                    break
                page_ +="#Subheading:"+headline+"\n"
                continue
            if tag.name == 'h3':
                headline = tag.get_text().strip()
                page_ +="##Subheading:"+headline+"\n"


            text = tag.get_text().strip()
            if len(text.split(" ")) > min_token and len(text.split(".")) > 1: # 多于min_token,.多于2
                text = clean_str(text).strip('\n\r')
                if text[-1] not in  ['.','?','!']:
                    text += '.'
                page_ += text + '\n'

        # 处理歧义页
        if "may refer to:" in page_.lower():
            obs, entity = search_step("[" + entity + "]",min_token,output_more)
        else:
            obs = get_page_obs(page_)
            if not output_more:
                index = min(len(obs),10)
                obs = obs[:index]
            

    return obs, entity

# 获取所有子分类
def get_sub_category(theme):
    site = pywikibot.Site('en', 'wikipedia')
    cat = pywikibot.Category(site, theme)
    subcategories_gen = cat.subcategories()
    # for subcat in subcategories_gen:
    #     print(subcat)
    # 将生成器转换为列表，并提取标题
    subcategory_titles = [subcat.title(with_ns=False) for subcat in subcategories_gen]
    return subcategory_titles




 # doc_id = f"doc_{hash(doc_text[0]) % 10000}"

if __name__ == '__main__':
    category = 'Renaissance'
    # related_category = search_related_pages(category)
    # print(related_category)
    # print(related_category)
    # get_sub_category(category)
    # views = get_pageviews(category)
    # print(views)
    pars,entity = search_step(category,output_more=True)
    with open("a1.json", 'w', encoding='utf-8') as f:
        json.dump(pars, f, ensure_ascii=False, indent=4)

    # theme = 'history'
    # theme = "History by period"
    # theme = 'history'
    # category = get_sub_category(theme)
    # print(category)
