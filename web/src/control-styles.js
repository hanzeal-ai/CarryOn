import {cva} from "class-variance-authority";
import {cn} from "./lib/utils";

const buttonVariants=cva("inline-flex items-center justify-center whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",{variants:{variant:{default:"bg-primary text-primary-foreground hover:bg-primary/90",destructive:"bg-destructive text-destructive-foreground hover:bg-destructive/90",outline:"border border-input bg-background hover:bg-accent hover:text-accent-foreground",secondary:"bg-secondary text-secondary-foreground hover:bg-secondary/80",ghost:"hover:bg-accent hover:text-accent-foreground",link:"text-primary underline-offset-4 hover:underline"},size:{default:"h-9 px-4 py-2",sm:"h-8 rounded-md px-3 text-xs",lg:"h-10 rounded-md px-8",icon:"h-9 w-9"}},defaultVariants:{variant:"outline",size:"default"}});
const inputClasses="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm shadow-sm transition-colors file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";
const textareaClasses="flex min-h-[60px] w-full rounded-md border border-input bg-transparent px-3 py-2 text-sm shadow-sm placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50";

// Decorate the existing DOM so focus, listeners and browser-owned input state survive.
export function styleControls(root=document){
  for(const element of root.querySelectorAll("button")){
    const variant=element.classList.contains("primary")?"default":element.classList.contains("danger-text")?"destructive":element.classList.contains("quiet")?"ghost":"outline";
    const size=element.classList.contains("copy")?"sm":"default";
    element.className=cn(buttonVariants({variant,size}),element.className);
  }
  for(const element of root.querySelectorAll("input"))element.className=cn(inputClasses,element.className);
  for(const element of root.querySelectorAll("textarea"))element.className=cn(textareaClasses,element.className);
}
