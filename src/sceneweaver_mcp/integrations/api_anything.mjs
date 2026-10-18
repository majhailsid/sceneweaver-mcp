// Optional API-Anything transport: fixed, public, read-only catalog operations.
import {lookup} from 'node:dns/promises';
import https from 'node:https';
import {BlockList, isIP} from 'node:net';
import {pathToFileURL} from 'node:url';

const deny = new BlockList();
let transportStatus;
for (const [address, prefix] of [['0.0.0.0',8],['10.0.0.0',8],['100.64.0.0',10],['127.0.0.0',8],
  ['169.254.0.0',16],['172.16.0.0',12],['192.0.0.0',24],['192.0.2.0',24],['192.168.0.0',16],
  ['192.88.99.0',24],['198.18.0.0',15],['198.51.100.0',24],['203.0.113.0',24],['224.0.0.0',4],['240.0.0.0',4]]) deny.addSubnet(address,prefix,'ipv4');
function publicIP(ip) {
  if (isIP(ip) === 4) return !deny.check(ip,'ipv4');
  const global = new BlockList();global.addSubnet('2000::',3,'ipv6');
  const special = new BlockList();
  special.addSubnet('2001::',23,'ipv6');special.addSubnet('2001:db8::',32,'ipv6');special.addSubnet('2002::',16,'ipv6');
  return isIP(ip) === 6 && global.check(ip,'ipv6') && !special.check(ip,'ipv6');
}
function permitted(value) {
  const u = new URL(value);
  if (u.protocol !== 'https:' || u.username || u.password || u.port || u.hash ||
      !((u.hostname === 'commons.wikimedia.org' && u.pathname === '/w/api.php') ||
        (u.hostname === 'api.openverse.org' && u.pathname === '/v1/images/') ||
        (u.hostname === 'www.pexels.com' && /^\/search\/videos\/[^/]+\/$/.test(u.pathname) && !u.search))) throw Error('Destination denied');
  return u;
}
async function fixedFetch(value, options={}) {
  const u = permitted(value);
  if (options.method && options.method !== 'GET') throw Error('Only GET allowed');
  const answers = await lookup(u.hostname,{all:true});
  if (!answers.length || answers.some(a=>!publicIP(a.address))) throw Error('Non-public address denied');
  const address = answers.find(a=>a.family===4) ?? answers[0];
  return new Promise((resolve,reject)=>{
    const req=https.request(u,{method:'GET',timeout:20000,
      lookup:(_host,options,cb)=>options?.all ? cb(null,[address]) : cb(null,address.address,address.family),
      headers:{'accept-encoding':'identity','user-agent':'SceneWeaver-MCP/0.1 (local media search)'}},res=>{
      const chunks=[];let size=0;
      res.on('data',c=>{size+=c.length;if(size>8*1024**2){req.destroy(Error('Response too large'));return;}chunks.push(c);});
      res.on('error',reject);
      res.on('end',()=>{
        let body=Buffer.concat(chunks);
        if([401,403,429].includes(res.statusCode)) transportStatus=({401:'auth',403:'blocked',429:'rate'})[res.statusCode];
        if(res.statusCode===200&&u.hostname!=='www.pexels.com') {
          try {
            const raw=JSON.parse(body.toString('utf8'));
            const fields=['id','title','url','foreign_landing_url','thumbnail','creator','license','license_url','mature','width','height'];
            if(Array.isArray(raw.results)) body=Buffer.from(JSON.stringify({results:raw.results.slice(0,12).map(r=>Object.fromEntries(fields.map(k=>[k,r[k]])))}));
            else if(Array.isArray(raw.query?.pages)) body=Buffer.from(JSON.stringify({query:{pages:raw.query.pages.slice(0,12).map(p=>({
              pageid:p.pageid,title:p.title,imageinfo:(p.imageinfo??[]).slice(0,1).map(i=>({url:i.url,thumburl:i.thumburl,
                descriptionurl:i.descriptionurl,width:i.width,height:i.height,mime:i.mime,
                extmetadata:Object.fromEntries(['Artist','Attribution','Credit','LicenseShortName','LicenseUrl','Restrictions'].map(k=>[k,i.extmetadata?.[k]]))}))}))}}));
          } catch {
            if(String(res.headers['content-type']).includes('text/html')) transportStatus='blocked';
            reject(Error('Invalid catalog JSON'));return;
          }
        }
        resolve(new Response(body,{status:res.statusCode,headers:{'content-type':res.headers['content-type']??''}}));
      });
    });
    req.on('error',reject);req.on('timeout',()=>req.destroy(Error('Timeout')));req.end();
  });
}
async function main() {
  const [provider,query,kind]=process.argv.slice(2);
  if (!['commons','openverse','pexels'].includes(provider) || !query || query.length>80 || /[\x00-\x1f]/.test(query) || !['mixed','image','video'].includes(kind)) throw Error('Invalid operation');
  const {call,parseSite,saveSite}=await import(pathToFileURL(process.env.SCENEWEAVER_API_ANYTHING_MODULE).href);
  let url,slot;
  if(provider==='commons') {
    url='https://commons.wikimedia.org/w/api.php?'+new URLSearchParams({action:'query',format:'json',formatversion:'2',generator:'search',gsrsearch:'water',gsrnamespace:'6',gsrlimit:'12',prop:'imageinfo',iiprop:'url|size|mime|extmetadata',iiurlwidth:'1920'});
    slot='query:gsrsearch';
  } else if(provider==='openverse') {
    url='https://api.openverse.org/v1/images/?'+new URLSearchParams({q:'water',page_size:'12',license:'cc0,pdm,by',source:'flickr',mature:'false'});
    slot='query:q';
  } else {
    url='https://www.pexels.com/search/videos/water/';slot='path:2';
  }
  const u=permitted(url);
  const site=parseSite({name:'sceneweaver-'+provider,baseUrl:u.origin,operations:[{
    name:'search',request:{method:'GET',url},slots:[{param:'query',at:[slot]}],trigger:{url},
    match:{method:'GET',host:u.hostname,path:provider==='pexels'?'/search/videos/*/':u.pathname},
    params:[{name:'query',type:'string',required:true,pattern:'.{1,100}'}],
    response:provider==='pexels'?{format:'html',html:{items:'a[href*="/download/video/"]',fields:{download_url:'@href'}}}:{format:'json'},
    readOnly:true,minTier:1,learnedLoggedIn:false}]});
  saveSite(site);
  const result=await call(site.name,'search',{query:query+(provider==='commons'&&kind==='video'?' filetype:video':'')},
    {maxTier:1,allowWrites:false,timeoutMs:22000,fetchImpl:fixedFetch});
  if(!result.ok) {
    console.log(JSON.stringify({ok:false,status:transportStatus??(['auth','rate','blocked'].includes(result.class)?result.class:'error')}));return;
  }
  if(provider==='pexels'&&(!Array.isArray(result.data)||!result.data.length)) {
    console.log(JSON.stringify({ok:false,status:'blocked'}));return;
  }
  console.log(JSON.stringify({ok:true,data:result.data}));
}
main().catch(()=>{console.log(JSON.stringify({ok:false,status:transportStatus??'error'}));process.exitCode=1;});
