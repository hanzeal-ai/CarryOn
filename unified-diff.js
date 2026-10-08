'use strict';
const UnifiedDiff = (() => {
  function lines(patch) {
    let old=0,next=0,left=0,right=0;
    return String(patch).split('\n').map((text,id)=>{
      const row={id,text,old:null,new:null,kind:'header',location:null};
      if(text.startsWith('@@')){
        left=right=0;
        const match=/^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(?: .*)?$/.exec(text);
        if(match){const values=[Number(match[1]),Number(match[2]??1),Number(match[3]),Number(match[4]??1)];
          if(values.every(Number.isSafeInteger)&&Number.isSafeInteger(values[0]+values[1])&&Number.isSafeInteger(values[2]+values[3]))[old,left,next,right]=values;}
        return row;
      }
      if(text.startsWith('\\ No newline'))return row;
      if(text.startsWith('+')&&right>0){row.new=next++;right--;row.kind='added';}
      else if(text.startsWith('-')&&left>0){row.old=old++;left--;row.kind='removed';}
      else if(text.startsWith(' ')&&left>0&&right>0){row.old=old++;row.new=next++;left--;right--;row.kind='context';}
      else {left=right=0;return row;}
      row.location=row.new===null?'L'+row.old:'R'+row.new;return row;
    });
  }
  return {lines};
})();
if(typeof module!=='undefined')module.exports=UnifiedDiff;
