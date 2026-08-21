# The Trees That Weren't There

*What a Finnish forest taught me about trusting my own metrics*

---

I built a tree detector. It scored 78.4% recall and 98.6% precision against 450
trees whose exact positions I knew, because I had generated them myself. Nice
numbers. I wrote them in a README and felt good about it.

Then I spent a week finding out what they meant, and the short version is: less
than I thought, and something else instead.

---

## The first thing that broke

The detector finds trees as local maxima on a canopy height model — a raster of
how tall the vegetation is above the ground. Tree tops are high points, so you
smooth the surface slightly and look for pixels taller than their neighbours.
It's the standard approach and it works.

The question I wanted to answer was how much LiDAR you need. Finland publishes
free canopy data at 0.5 points per square metre. My synthetic sample was 6.34.
Thirteen times denser. So: how badly does detection degrade as data thins?

I had ground truth, so I could actually measure it. Decimate the point cloud to
0.5, 1, 2, 4 points per square metre, rebuild the canopy model at each, re-score
against the same 450 trees.

Recall went **up**.

At full density, 78.4%. At the sparsest, 81.8%. Sparse data found more trees.

That is not a result. That is a warning light. And the explanation is in the
columns I hadn't been looking at: precision fell from 98.6% to 92.0%, false
positives went from 5 to 32, and height error quadrupled from 0.44 m to 1.63 m.

At half a point per square metre, a one-metre canopy raster has more empty cells
than filled ones. Missing data gets written as zero. The surface becomes a field
of isolated spikes separated by artificial valleys, and that roughness generates
extra local maxima. Some of them, by luck, land near real trees. Recall rises.

F1 hid it completely — 86.6 at the worst density, 87.4 at the best.

**Position can be faked by noise. Height cannot.** I'd been reporting the
gameable metric.

---

## Real forest, and a bias that hid in plain sight

Synthetic data has a ceiling. My generated stand was about 28 stems per hectare,
which meant crowns barely touched — the easy case. I needed real forest.

Finland turned out to be the right answer for a reason I hadn't anticipated.
The famous Finnish LiDAR isn't free (it needs payment and Finnish bank
credentials, which as an American I simply cannot obtain). But the Finnish
Forest Centre publishes something better for my purposes: finished canopy height
models derived from that licensed data, at one metre, openly licensed, no
registration. And alongside them, the actual forest inventory — stand polygons
with measured heights, basal areas, species, and a professional management plan
listing which stands foresters intend to cut between 2026 and 2035.

Real ground truth. Not mine.

I pulled three epochs for one 6 km map sheet near Nuuksio National Park: 2008,
2015, 2020. Twelve years of canopy change over 3,600 hectares.

The mean canopy height went 9.78 m → 12.25 m → 12.37 m.

Look at that middle number. Two and a half metres of growth in seven years, then
twelve centimetres in five. Forests don't do that.

My first thought was harvest. But harvest in the second period was 3.6% versus
2.6% in the first — nowhere near enough. My second thought was calibration
error, so I built a check: find pixels that were bare ground in the earlier
epoch, and compare them. Ground is ground. It should read zero in any flight,
and any systematic difference is the sensor, not the trees.

The ground offset came back **+0.00 m**. All three epoch pairs. Perfect
agreement.

I took that as reassurance. It wasn't. My check verified *ground* calibration
and was structurally incapable of saying anything about *canopy*.

The test that worked was stratifying the change by tree size. Real height growth
falls off steeply as trees get big — a young stand adds half a metre a year, a
30-metre spruce adds maybe a tenth. So if I bin pixels by starting height and
the growth rate doesn't decline, something is wrong.

There's a trap here I walked into first. If you bin by the same measurement
you're differencing, you get regression to the mean: a pixel lands in the tall
bin partly because noise pushed it up, and that noise doesn't repeat, so it
drifts down on remeasurement regardless of biology. My first run showed exactly
the textbook decay curve and I believed it.

Having three epochs, I could bin on the middle one instead — its noise is
independent of both endpoints. Redone properly:

```
 3–8 m    +0.247 m/yr
 8–15 m   +0.319
15–22 m   +0.296
22–28 m   +0.263
28–60 m   +0.308     ← should be near zero
```

Flat. Completely flat. Trees thirty metres tall growing as fast as trees eight
metres tall, which does not happen. A constant gain regardless of size isn't
growth, it's an offset — the 2008 flight measured **canopy** low while measuring
**ground** correctly.

So the honest conclusion about my twelve-year growth figure is that I don't have
one. An additive bias preserves *ordering*, so I can still say which stands grew
more than others. I cannot say how much.

That felt like failure for about an hour. It isn't. Knowing which claim your
data can't support is the job.

---

## What the inventory actually said

Then the good part. I could finally check detection against a real forest
inventory — 1,840 stands, measured by people on the ground.

I'd been telling myself Finnish forest runs 800 to 1,500 stems per hectare. The
inventory says the median is **496**, and 444 in mature stands. My number was
for young unthinned forest, not forest at rotation age. I'd been quoting it for
days.

Against the real figure, my detector recovers **16%** of stems. One in six.

That sounds bad until you see how it's distributed:

| stand type | inventory | detected | recovered |
|---|---|---|---|
| young thinning | 817 | 87 | 12% |
| advanced thinning | 635 | 87 | 15% |
| regeneration-mature | 444 | 70 | **17%** |

Monotonic with maturity. As stands age and thin, crowns get bigger and further
apart, and more of them resolve. That's not noise — that's the physics of the
method showing up across 1,295 real stands. A canopy model sees the overstory.
Everything suppressed beneath it is invisible, and no amount of cleverness in
the peak-finder changes that.

And then the number I actually care about.

I compared canopy heights two ways without thinking much about it, and got
opposite answers:

```
detected stems only    20.83 m   (+1.19 above inventory)
inventory mean          19.64 m
all CHM pixels          15.69 m   (−3.95 below inventory)
```

They bracket the truth. Which makes sense once you see it: detected stems are
crown *apexes*, so they sit above a stem-weighted mean that includes shorter
trees. The whole-pixel average sits below because it includes canopy gaps —
about one pixel in ten is a hole.

Same raster. Same forest. Opposite sign. And the stem-based estimator correlates
better with the inventory: **r = 0.962** versus 0.901.

One more thing mattered here, and I nearly skipped it. The inventory
observations run from 1999 to 2024 — some stands were last measured two decades
before the canopy scan. Dropping anything measured more than six years from the
raster took the correlation from 0.907 to 0.962. Twenty minutes of date
filtering bought more accuracy than any tuning I did to the detector.

So the real finding, the one I'd actually defend: **a canopy height model
measures dominant tree height to within about 1.2 m of a national forest
inventory, at r = 0.96, while counting roughly one stem in six.** Good at height. Bad at counting. And which of those you get depends
entirely on which average you compute — a detail I'd have breezed past a week
ago.

---

## The result I nearly didn't report

Last piece. The inventory includes a real management plan, so I could score my
harvest ranking against decisions professional foresters had already made. This
was going to be the payoff: *my algorithm agrees with the experts.*

It did. 15 out of 15. Precision 100%.

And it means nothing.

Because once you filter stands to development class 04 — *uudistuskypsä*,
"regeneration-ripe", a forester's own judgement that a stand has reached
rotation age — **471 of 472 eligible stands were already on the cutting list.**
The base rate in my candidate pool was 100%. Lift over random: 1.00×.

I couldn't have been wrong. The classification did all the work; the canopy data
added nothing on top of it.

(An earlier version of this benchmark reported 1.37× lift, because I'd computed
the base rate across all stands instead of the pool I was actually choosing
from. That credits the ranking for exclusions the development class had already
made. Wrong denominator, flattering number.)

There's a version of this project where I don't run that check, publish the
100%, and it sounds great. The check took twenty minutes and turned a headline
into a caveat. That's the right trade.

---

## What I'd tell someone starting this

Report height error, not recall. Recall improved as my data got worse.

Check your calibration on the thing you're measuring. Perfect ground agreement
told me nothing about canopy, and I nearly let it reassure me.

Watch out for one-sided sanity checks. Mine flagged implausibly *fast* growth
and sailed straight past mature forest apparently shrinking, because I'd only
written a ceiling.

Say which estimator produced your number. Two reasonable definitions of "mean
canopy height" differed by five metres and landed on opposite sides of the
truth.

And score against the pool you actually chose from. Almost every inflated
accuracy claim I've seen — my own included — comes from a denominator that
quietly includes cases the method never had to discriminate.

The forest was there the whole time. It just took a national inventory to tell
me what I was really looking at.

---

*Canopy height models and forest resource data: Suomen metsäkeskus / Finnish
Forest Centre, CC BY 4.0. Code and full technical report:
[github.com/bdgroves/lidar-explore](https://github.com/bdgroves/lidar-explore)*
