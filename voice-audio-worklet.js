/* Capture PCM16LE at 24 kHz. The requested AudioContext rate is verified by the client. */
class CarryOnCapture extends AudioWorkletProcessor {
  constructor(){super();this.samples=new Float32Array(2400);this.length=0;}
  process(inputs){
    const input=inputs[0]?.[0];if(!input)return true;
    for(const sample of input){
      this.samples[this.length++]=sample;
      if(this.length===this.samples.length){
        const bytes=new ArrayBuffer(this.length*2),view=new DataView(bytes);
        for(let i=0;i<this.length;i++){const v=Math.max(-1,Math.min(1,this.samples[i]));view.setInt16(i*2,Math.round(v*(v<0?32768:32767)),true);}
        this.port.postMessage(bytes,[bytes]);this.length=0;
      }
    }
    return true;
  }
}
registerProcessor('carryon-capture',CarryOnCapture);
