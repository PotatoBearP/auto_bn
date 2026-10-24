"""Current-event enemy and obstacle sprites, calibrated from live deployment."""
from functools import lru_cache
from PIL import Image, ImageChops, ImageStat
from paths import TEMPLATES


@lru_cache(maxsize=1)
def references():
    enemies=[];obstacles=[]
    for path in TEMPLATES.glob('attrition-enemy-*.png'):
        with Image.open(path) as image:
            enemies.append((path.stem.split('-')[2],image.convert('RGB').resize((22,20))))
    for path in TEMPLATES.glob('attrition-obstacle-*.png'):
        with Image.open(path) as image:
            obstacles.append(image.convert('RGB').resize((35,20)))
    return enemies,obstacles


def difference(a,b):
    return sum(ImageStat.Stat(ImageChops.difference(a,b)).mean)/3


@lru_cache(maxsize=1)
def air_references():
    result=[]
    for path in TEMPLATES.glob('attrition-air-core-*.png'):
        with Image.open(path) as image: result.append(image.convert('RGB').resize((26,36)))
    return result


def air_cells(image):
    from battle_rules import CELLS,position
    found=[]
    for cell in CELLS:
        x,y=position(cell)
        matched=False
        for dx in (-4,0,4):
            for dy in (-8,-4,0,4,8):
                # Narrow head/torso crop excludes the moving wing tips. The
                # upper-body red marks distinguish it from the lower bat.
                crop=image.crop((x-16+dx,y-102+dy,x+23+dx,y-48+dy)).convert('RGB')
                red=sum(r>110 and r>g*1.5 and r>b*1.5 for r,g,b in crop.getdata())
                if red<120: continue
                sample=crop.resize((26,36))
                if any(difference(sample,ref)<28 for ref in air_references()):
                    matched=True;break
            if matched: break
        if matched: found.append(cell)
    return found


def obstacle_at(image,foot):
    x,y=foot
    return any(difference(image.crop((x-35+dx,y-55+dy,x+35+dx,y-15+dy)).convert('RGB').resize((35,20)),ref)<23
               for dx in (-4,0,4) for dy in (-4,0,4) for ref in references()[1])


def enemies(image,include_air=False):
    from battle_rules import CELLS,position
    found=[]
    airborne=set(air_cells(image))
    for row,col in CELLS:
        x,y=position((row,col))
        if (row,col) in airborne:
            if include_air:
                found.append({'foot':[x,y],'side':'enemy','row':row,'column':col,
                              'sprite':'airflyer','hp_fraction':1.,'hp_source':'full_without_bar'})
            continue
        if obstacle_at(image,(x,y)): continue
        colors=image.crop((x-22,y-55,x+22,y-15)).convert('RGB').getdata()
        red=sum(r>100 and r>g*1.5 and r>b*1.5 for r,g,b in colors)
        if red<30: continue
        best=(999,None,999)
        for dx in (-4,0,4):
            for dy in (-4,0,4):
                sample=image.crop((x-22+dx,y-55+dy,x+22+dx,y-15+dy)).convert('RGB').resize((22,20))
                for name,ref in references()[0]:
                    score=difference(sample,ref)
                    if score<36:
                        core=difference(sample.crop((5,3,18,18)),ref.crop((5,3,18,18)))
                        if (score<25 or (core<23 and red>=80)) and score<best[0]:
                            best=(score,name,core)
        # Outlines and idle poses alter the crop edges much more than the
        # torso. Permit that variation only with a matching central body and
        # clear enemy colors; empty tiles and rubble still fail both checks.
        if best[1] is not None:
            if best[1]=='airflyer' and not include_air: continue
            found.append({'foot':[x,y],'side':'enemy','row':row,'column':col,
                          'sprite':best[1],'hp_fraction':1.,'hp_source':'full_without_bar'})
    return found
