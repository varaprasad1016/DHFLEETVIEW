import{i as e}from"./rolldown-runtime-Dd_uD5pT.js";import{H as t,N as n,St as r,Tt as i,U as a,W as o,dt as s,et as c,lt as l,qt as u,ut as d,wt as f}from"./mui-CBkZBVSu.js";function p(e){return String(e).match(/[\d.\-+]*\s*(.*)/)[1]||``}function m(e){return parseFloat(e)}var h=e(u(),1);function g(e){return d(`MuiSkeleton`,e)}l(`MuiSkeleton`,[`root`,`text`,`rectangular`,`rounded`,`circular`,`pulse`,`wave`,`withChildren`,`fitContent`,`heightAuto`]);var _=r(),v=e=>{let{classes:t,variant:n,animation:r,hasChildren:i,width:a,height:o}=e;return c({root:[`root`,n,r,i&&`withChildren`,i&&!a&&`fitContent`,i&&!o&&`heightAuto`]},g,t)},y=i`
  0% {
    opacity: 1;
  }

  50% {
    opacity: 0.4;
  }

  100% {
    opacity: 1;
  }
`,b=i`
  0% {
    transform: translateX(-100%);
  }

  50% {
    /* +0.5s of delay between each loop */
    transform: translateX(100%);
  }

  100% {
    transform: translateX(100%);
  }
`,x=typeof y==`string`?null:f`
        animation: ${y} 2s ease-in-out 0.5s infinite;
      `,S=typeof b==`string`?null:f`
        &::after {
          animation: ${b} 2s linear 0.5s infinite;
        }
      `,C=o(`span`,{name:`MuiSkeleton`,slot:`Root`,overridesResolver:(e,t)=>{let{ownerState:n}=e;return[t.root,t[n.variant],n.animation!==!1&&t[n.animation],n.hasChildren&&t.withChildren,n.hasChildren&&!n.width&&t.fitContent,n.hasChildren&&!n.height&&t.heightAuto]}})(a(({theme:e})=>{let t=p(e.shape.borderRadius)||`px`,r=m(e.shape.borderRadius),i=n(e,{animation:`none`}),a=n(e,{"&::after":{animation:`none`,display:`none`}});return{display:`block`,backgroundColor:e.vars?e.vars.palette.Skeleton.bg:e.alpha(e.palette.text.primary,e.palette.mode===`light`?.11:.13),height:`1.2em`,variants:[{props:{variant:`text`},style:{marginTop:0,marginBottom:0,height:`auto`,transformOrigin:`0 55%`,transform:`scale(1, 0.60)`,borderRadius:`${r}${t}/${Math.round(r/.6*10)/10}${t}`,"&:empty:before":{content:`"\\00a0"`}}},{props:{variant:`circular`},style:{borderRadius:`50%`}},{props:{variant:`rounded`},style:{borderRadius:(e.vars||e).shape.borderRadius}},{props:({ownerState:e})=>e.hasChildren,style:{"& > *":{visibility:`hidden`}}},{props:({ownerState:e})=>e.hasChildren&&!e.width,style:{maxWidth:`fit-content`}},{props:({ownerState:e})=>e.hasChildren&&!e.height,style:{height:`auto`}},{props:{animation:`pulse`},style:x||{animation:`${y} 2s ease-in-out 0.5s infinite`}},...i?[{props:{animation:`pulse`},style:i}]:[],{props:{animation:`wave`},style:{position:`relative`,overflow:`hidden`,WebkitMaskImage:`-webkit-radial-gradient(white, black)`,"&::after":{background:`linear-gradient(
                90deg,
                transparent,
                ${(e.vars||e).palette.action.hover},
                transparent
              )`,content:`""`,position:`absolute`,transform:`translateX(-100%)`,bottom:0,left:0,right:0,top:0}}},{props:{animation:`wave`},style:S||{"&::after":{animation:`${b} 2s linear 0.5s infinite`}}},...a?[{props:{animation:`wave`},style:a}]:[]]}})),w=h.forwardRef(function(e,n){let r=t({props:e,name:`MuiSkeleton`}),{animation:i=`pulse`,className:a,component:o=`span`,height:c,style:l,variant:u=`text`,width:d,...f}=r,p={...r,animation:i,component:o,variant:u,hasChildren:!!f.children},m=v(p);return(0,_.jsx)(C,{as:o,ref:n,className:s(m.root,a),ownerState:p,...f,style:{width:d,height:c,...l}})});export{w as t};