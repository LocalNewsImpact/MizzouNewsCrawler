#!/usr/bin/env python3
"""Check whether RTCPeerConnection still yields ICE candidates after our stub injection."""
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
import time

def main():
    options = Options()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument('--start-maximized')
    options.add_argument('--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    options.add_experimental_option('useAutomationExtension', False)

    service = Service('/home/appuser/chromedriver')
    driver = webdriver.Chrome(service=service, options=options)

    # Inject the same stubs we used in the run script
    driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
        'source': """
(function(){
  try {
    const tz='America/Chicago';
    const origGet=Date.prototype.getTimezoneOffset;
    Date.prototype.getTimezoneOffset=function(){try{const l=new Date(this.valueOf());const t=new Date(l.toLocaleString('en-US',{timeZone:tz}));return Math.round((l.getTime()-t.getTime())/60000);}catch(e){return origGet.call(this);}};
    const origR=Intl.DateTimeFormat.prototype.resolvedOptions;Intl.DateTimeFormat.prototype.resolvedOptions=function(){const r=origR.call(this);r.timeZone=tz;return r;};
  }catch(e){}
  try{
    class FakeRTCPeerConnection{constructor(){this._listeners={};}addEventListener(t,l){this._listeners[t]=this._listeners[t]||[];this._listeners[t].push(l);}removeEventListener(t,l){if(this._listeners[t])this._listeners[t]=this._listeners[t].filter(x=>x!==l);}close(){}createDataChannel(){return{}}createOffer(){return Promise.resolve({});}createAnswer(){return Promise.resolve({});}setLocalDescription(){return Promise.resolve();}setRemoteDescription(){return Promise.resolve();}addIceCandidate(){return Promise.resolve();}getStats(){return Promise.resolve([]);} }
    Object.defineProperty(window,'RTCPeerConnection',{value:FakeRTCPeerConnection,configurable:true});Object.defineProperty(window,'webkitRTCPeerConnection',{value:FakeRTCPeerConnection,configurable:true});Object.defineProperty(window,'mozRTCPeerConnection',{value:FakeRTCPeerConnection,configurable:true});
    try{Object.defineProperty(window,'RTCIceCandidate',{value:function(){return{}},configurable:true});}catch(e){}
    if(!navigator.mediaDevices)navigator.mediaDevices={};navigator.mediaDevices.getUserMedia=function(){return Promise.reject(new Error('getUserMedia disabled'));};navigator.mediaDevices.enumerateDevices=function(){return Promise.resolve([]);}  }catch(e){}
})();
    """
    })

    # Now load a minimal page that forces an RTCPeerConnection and waits for candidate
    html = """
<html><body><pre id='out'></pre><script>
(async function(){
  try{
    var out=document.getElementById('out');
    var pc = new RTCPeerConnection({iceServers:[]});
    var candidates=[];
    pc.onicecandidate = function(e){ if (e && e.candidate) candidates.push(e.candidate.candidate); };
    pc.createDataChannel('x');
    try{ let offer = await pc.createOffer(); await pc.setLocalDescription(offer);}catch(e){ out.innerText='offer_error:'+e.message; return; }
    await new Promise(r=>setTimeout(r,2000));
    if(candidates.length) out.innerText='CANDIDATES:'+candidates.join(';'); else out.innerText='NO_CANDIDATES';
  }catch(e){ document.getElementById('out').innerText='ERROR:'+e.message }
})();
</script></body></html>
"""

    driver.get('data:text/html,'+html)
    # wait
    import time
    for _ in range(6):
        v = driver.find_element('tag name','pre').text
        if v and v!='':
            print('Result:', v)
            break
        time.sleep(1)
    else:
        print('No result')

    driver.quit()


if __name__ == '__main__':
    main()
