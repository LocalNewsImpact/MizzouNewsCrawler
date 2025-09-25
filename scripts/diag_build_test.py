from src.crawler.discovery import NewsDiscovery

if __name__ == '__main__':
    nd = NewsDiscovery(timeout=10, delay=0.0)
    # Allow build - this will run the process-based worker with timeout
    res = nd.discover_with_newspaper4k('https://www.4bcaonline.com', allow_build=True)
    print('Discovered:', len(res))
    for r in res[:10]:
        print(r)
