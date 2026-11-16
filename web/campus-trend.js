'use strict';

// Only expanded trend panels load the local chart bundle.
(() => {
  let library;
  function loadLibrary() {
    if(window.echarts)return Promise.resolve(window.echarts);
    if(!library)library=new Promise((resolve,reject)=>{
      const script=document.createElement('script');
      script.src='/assets/vendor/echarts/echarts.common.min.js?v=6.1.0';
      script.onload=()=>window.echarts?resolve(window.echarts):reject(new Error('chart'));
      script.onerror=()=>{script.remove();reject(new Error('chart'));};
      document.head.append(script);
    }).catch(error=>{library=null;throw error;});
    return library;
  }

  function plotPoints(records) {
    const points=[];
    let previous=null;
    for(const record of records) {
      const index=Number(record.term.slice(0,4))*2+Number(record.term.slice(-1));
      if(previous!==null&&index>previous+1)points.push({term:'…',gpa:null});
      points.push(record);
      previous=index;
    }
    return points;
  }

  class CampusGpaChart extends HTMLElement {
    connectedCallback() {
      this.panel=this.closest('details');
      this.onToggle=()=>this.update();
      this.revision=0;
      this.panel?.addEventListener('toggle',this.onToggle);
      this.update();
    }
    disconnectedCallback() {
      this.panel?.removeEventListener('toggle',this.onToggle);
      this.revision++;
      this.release();
    }
    release() {
      this.resizeObserver?.disconnect();
      this.instance?.dispose();
      this.resizeObserver=null;
      this.instance=null;
      this.replaceChildren();
      this.removeAttribute('aria-busy');
    }
    async update() {
      const revision=++this.revision;
      if(this.panel&&!this.panel.open){this.release();return;}
      if(this.instance)return;
      if(!this.clientWidth){
        this.resizeObserver?.disconnect();
        this.resizeObserver=new ResizeObserver(()=>{
          if(this.clientWidth){this.resizeObserver.disconnect();this.update();}
        });
        this.resizeObserver.observe(this);
        return;
      }
      this.setAttribute('aria-busy','true');
      this.textContent='正在打开趋势图…';
      try {
        const echarts=await loadLibrary();
        if(!this.isConnected||(this.panel&&!this.panel.open)||revision!==this.revision)return;
        const points=plotPoints(JSON.parse(this.dataset.points));
        this.replaceChildren();
        const style=getComputedStyle(this);
        this.instance=echarts.init(this,null,{renderer:'svg'});
        this.instance.setOption({
          animation:false,
          color:[style.getPropertyValue('--blue').trim()],
          textStyle:{fontFamily:style.fontFamily,color:style.color},
          grid:{left:36,right:20,top:24,bottom:34},
          tooltip:{trigger:'axis',renderMode:'richText',confine:true},
          xAxis:{type:'category',data:points.map(x=>x.term),boundaryGap:true,
            axisLabel:{hideOverlap:true,formatter:value=>value.replace(/^20(\d\d)-20(\d\d)-([12])$/,'$1–$2·$3')}},
          yAxis:{type:'value',min:0,max:4,interval:1,splitLine:{lineStyle:{color:style.getPropertyValue('--line').trim()}}},
          series:[{name:'学期平均绩点',type:'line',connectNulls:false,data:points.map(x=>x.gpa),
            symbol:'circle',symbolSize:6,label:{show:points.length<=6,position:'top',formatter:p=>p.value==null?'':Number(p.value).toFixed(2)}}]
        });
        this.resizeObserver=new ResizeObserver(()=>{if(this.clientWidth&&this.instance)this.instance.resize();});
        this.resizeObserver.observe(this);
        this.removeAttribute('aria-busy');
      } catch {
        if(!this.isConnected||revision!==this.revision)return;
        this.release();
        this.textContent='趋势图暂时无法显示，可查看学期成绩表中的绩点。';
      }
    }
  }
  customElements.define('campus-gpa-chart',CampusGpaChart);
})();
