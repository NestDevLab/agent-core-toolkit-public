"""Bounded-memory reader for ncdu 1.x exports; no filesystem mutations."""
import gzip,json,heapq,sys

def events(handle):
    decoder=json.JSONDecoder(); buf=''; pos=0; eof=False
    while True:
        if pos>=len(buf) and not eof:
            buf=handle.read(65536);pos=0;eof=not buf
        while pos<len(buf) and buf[pos].isspace():pos+=1
        if pos==len(buf):
            if eof:return
            continue
        char=buf[pos]
        if char in '[],':
            pos+=1;yield char;continue
        while True:
            try:
                value,end=decoder.raw_decode(buf,pos)
                if end==len(buf) and not eof:
                    extra=handle.read(65536);eof=not extra;buf+=extra
                    if extra:continue
                pos=end;yield value;break
            except json.JSONDecodeError:
                if eof:raise
                extra=handle.read(65536)
                if not extra:raise ValueError('Incomplete JSON')
                buf=buf[pos:]+extra;pos=0
                if len(buf)>8388608:raise ValueError('Oversized metadata record')

def summary(handle):
    it=iter(events(handle)); header=[]
    for token in it:
        if token in ('[',','):continue
        header.append(token)
        if len(header)==3:break
    if header[:2]!=[1,2]:raise ValueError('Unknown ncdu version')
    stack=[];seen=set();top=[];errors=[];total=0;dirs=files=0;depth=1
    for token in it:
        if token=='[':
            depth+=1;stack.append(None)
        elif isinstance(token,dict):
            directory=bool(stack and stack[-1] is None)
            parent=stack[-2] if directory and len(stack)>1 else stack[-1] if not directory else None
            dev=token.get('dev',parent['dev'] if parent else None)
            path=(parent['path'].rstrip('/')+'/' if parent else '')+token.get('name','')
            size=token.get('dsize',token.get('asize',0))
            if token.get('hlnkc'):
                key=(dev,token.get('ino'))
                if None in key:errors.append('hardlink identity missing: '+path)
                elif key in seen:size=0
                else:seen.add(key)
            if token.get('read_error'):errors.append('read_error: '+path)
            if directory:
                dirs+=1;stack[-1]={'path':path,'size':size,'dev':dev}
            else:
                files+=1
                if stack:stack[-1]['size']+=size
        elif token==']':
            depth-=1
            if not stack:continue
            row=stack.pop()
            if row is None:raise ValueError('Missing directory metadata')
            if stack:stack[-1]['size']+=row['size']
            else:total=row['size']
            heapq.heappush(top,(row['size'],row['path']))
            if len(top)>60:heapq.heappop(top)
    if stack or depth!=0 or not dirs:raise ValueError('Incomplete directory export')
    return {'allocatedBytes':total,'directories':dirs,'files':files,'readErrors':len(errors),'errorSamples':errors[:10],'largest':sorted(top,reverse=True)}

