import fs from 'node:fs';
import assert from 'node:assert/strict';
import {chromium,webkit} from 'playwright';
const BASE=process.env.BASE||'http://127.0.0.1:4175';
const src=fs.readFileSync('/home/ubuntu/studyBridge/audit_reports/learningmate_ec2_e2e_20260924T142154Z/tools/browser_race.js','utf8');
const creds={email:src.match(/const EMAIL = '([^']+)'/)[1],password:src.match(/const PW = '([^']+)'/)[1]};
const results=[];
const map={pdfSummary:'/archive',roadmap:'/planner',quiz:'/archive',aiQna:'/studymate',groupStudy:'/groupstudy',progress:'/study-report'};
for(const [engine,widths] of [[chromium,[1280,360,393,430]],[webkit,[393,430]]]) {
 const browser=await engine.launch();
 for(const width of widths){
  const ctx=await browser.newContext({viewport:{width,height:900},ignoreHTTPSErrors:true});
  const page=await ctx.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));page.on('dialog',d=>d.accept());
  const rec=(name,detail={})=>{results.push({engine:engine.name(),width,name,...detail});console.log(engine.name(),width,name,JSON.stringify(detail));};
  try{
   await page.goto(BASE+'/login'); await page.locator('input[name=email]').fill(creds.email);await page.locator('input[name=password]').fill(creds.password);
   await page.locator('button[type=submit]').click(); await page.waitForURL(u=>!u.pathname.endsWith('/login'));
   for(const [key,to] of Object.entries(map)){await page.goto(BASE+'/');await page.locator(`[data-feature=${key}]`).click();await page.waitForURL(u=>u.pathname===to);await page.waitForLoadState('networkidle');await page.goBack();assert.equal(new URL(page.url()).pathname,'/');}
   rec('routing + back PASS');
   await page.goto(BASE+'/learning-mate');await page.waitForURL('**/studymate');await page.waitForLoadState('networkidle');rec('legacy redirect PASS');
   await page.goto(BASE+'/weekly-schedule');await page.locator('.fc-daygrid-day').first().waitFor();
   for(const w of width===360?[360,375,390,393,402,412,430,440]:[width]){
    await page.setViewportSize({width:w,height:900});await page.waitForTimeout(150);
    const metrics=await page.evaluate(()=>{const row=document.querySelector('.fc-daygrid-body tr');const cells=[...row.children];const input=document.querySelector('input[type=date]');return {columns:cells.length,overflow:Math.max(document.body.scrollWidth,document.documentElement.scrollWidth)-innerWidth,dateWidth:input?.getBoundingClientRect().width,dateParent:input?.parentElement.getBoundingClientRect().width,clipped:cells.some(c=>{const n=c.querySelector('.fc-daygrid-day-number');return n&&n.getBoundingClientRect().right>c.getBoundingClientRect().right+1})};});
    assert.equal(metrics.columns,7);assert.equal(metrics.overflow,0);assert.equal(metrics.clipped,false);assert.ok(metrics.dateWidth<=metrics.dateParent+1);rec('calendar + weekly PASS',{viewport:w,...metrics});
   }
   await page.setViewportSize({width,height:900});
   const material=await page.evaluate(async()=>{const r=await fetch('/api/materials',{headers:{Authorization:'Bearer '+localStorage.token}});return r.json();});
   const list=Array.isArray(material)?material:material.content||material.items||[];
   const journal=list.find(m=>m.materialType==='STUDY_LOG'||m.materialType==='JOURNAL');
   if(journal){await page.goto(BASE+'/archive/journal/'+journal.materialId);await page.locator('.archive-split-view').waitFor();await page.waitForTimeout(400);const m=await page.evaluate(()=>({columns:getComputedStyle(document.querySelector('.archive-split-view')).gridTemplateColumns,overflow:document.documentElement.scrollWidth-innerWidth,left:document.querySelector('.archive-left-panel')?.getBoundingClientRect().width}));assert.equal(m.overflow,0);if(width<769)assert.ok(m.left>width*.7);rec('journal PASS',m);}else rec('journal NO_FIXTURE');
   assert.equal(errors.length,0,errors.join(';'));rec('runtime PASS');
  }catch(e){rec('FAIL',{error:e.message.slice(0,350)});}
  await ctx.close();
 }
 await browser.close();
}
fs.writeFileSync('audit_reports/final-addon-2/browser.json',JSON.stringify(results,null,2));
if(results.some(r=>r.name==='FAIL'))process.exitCode=1;
