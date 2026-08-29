# Dog ethology and character-animation principles for Parcel: what the dog should DO and how to EVALUATE believability

Research note, 2026-08-28. Scope: canine ethology (looking back / gaze alternation, social referencing, play signals and the "dog-laugh", tail/posture emotion signals, attachment and greeting), robot-pet ethograms (Sony AIBO/aibo, MiRo), animation principles applied to robots, HRI believability instruments (Godspeed, RoSAS, and recent perception studies), and the Unitree Go2 Sport API action inventory. Ends with a proposed named behavior catalog (34 behaviors) with trigger contexts and Go2 mappings.

Method: every source below was fetched and read during this session (WebFetch, Europe PMC / OpenAlex / Semantic Scholar / Crossref APIs, GitHub raw files, or a downloaded PDF converted with pdftotext). Where only an abstract or metadata record could be retrieved, that is stated. Nothing is cited from memory. Web search budget was exhausted mid-session, so a few secondary items (Melson et al. 2009 children/AIBO percentages; Rehn & Keeling 2011 abstract; Byosiere 2016 adult-dog play-bow abstract; Bekoff 1995 percentages) could not be read in full and are flagged rather than used as evidence.

---

## Part A. Canine ethology

### A1. "Looking back" / gaze alternation in the unsolvable task

**A1.1 Miklosi et al. 2003, Current Biology 13:763-766. "A simple reason for a big difference: wolves do not look back at humans, but dogs do."**
- Source read: Europe PMC abstract record, PMID 12725735 (https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=EXT_ID:12725735&resultType=core&format=json). The Cell PDF and the animal-studies repository copy returned 403.
- What it says (abstract, verbatim in parts): dogs and wolves "socialized to humans at comparable levels"; Study 1: socialized wolves could use touching and, to some extent, pointing cues but "their performance remained inferior to that of dogs"; Study 2: "after undergoing training to solve a simple manipulation task, dogs that are faced with an insoluble version of the same problem look/gaze at the human, while socialized wolves do not." The authors "suggest that the key difference between dog and wolf behavior is the dogs' ability to look at the human's face."
- Numbers: none in the abstract. Marshall-Pescini et al. 2017 (A1.3) describe the subjects as 4-month-old pet dogs vs same-age wolves raised in a pet-like environment, and say dogs looked back "sooner and for longer". (Sample sizes are not in any text I fetched; do not quote N=9/9 from memory.)
- Assessment: canonical; single source for the original claim, but replicated many times since (A1.2-A1.5).

**A1.2 Marshall-Pescini, Viranyi, Range 2015, Biology Letters 11:20150489. "When dogs look back: inhibition of independent problem-solving behaviour in domestic dogs compared with wolves."**
- Source read: PMC full text (https://pmc.ncbi.nlm.nih.gov/articles/PMC4614426/).
- Design: 10 pet dogs, 10 shelter dogs, 10 hand-reared human-socialized wolves; up to three 2-minute trials on a *solvable* puzzle box; conditions: alone, human-in (experimenter neutral, 3 steps away), encouragement.
- Numbers: wolves 80% average success vs 5% for pet dogs and 5% for shelter dogs (human-in and alone combined). Dogs spent significantly more time gazing at the human; wolves focused on the box.
- Conclusion: dogs show "generalized dependence on, or deference to, human action"; looking back may reflect conditioned inhibition of independent problem solving rather than superior social cognition.

**A1.3 Marshall-Pescini, Rao, Viranyi, Range 2017, Scientific Reports 7:46636. "The role of domestication and experience in 'looking back' towards humans in an unsolvable task."**
- Sources read: Europe PMC abstract (PMID 28422169) and PMC full text (https://pmc.ncbi.nlm.nih.gov/articles/PMC5395970/).
- Design: wolves N=15, Wolf Science Center pack dogs N=14, pet dogs N=19, free-ranging dogs (India) N=11. Three solvable trials (3 min each) then one unsolvable trial extended to 3 min ("compared to most studies in which animals had just 1 or 2 minutes").
- Numbers: looked back at least once: wolves 11/15 (73%), pack dogs 14/14, pet dogs 19/19, free-ranging dogs 11/11. "Wolves were more persistent than all dog groups. Regardless of socialization or species, less persistent animals looked back sooner and longer." The longer an individual interacted with the apparatus, the later it looked back (LM F=11.9, p=0.001); more persistent animals also looked back for shorter durations and less often. When persistence was included, group differences disappeared.
- Conclusion (abstract): "once the human is considered a social partner, looking behaviour occurs easily"; species differences are in persistence/exploration rather than readiness to look.
- Assessment: LOAD-BEARING for Parcel. The computational content is: look-back is triggered by *giving up on a task* (a persistence budget running out), modulated by whether the human is a social partner. This is directly implementable as a learned/tunable persistence threshold.

**A1.4 Lazzaroni et al. 2020, Animal Cognition. "Why do dogs look back at the human in an impossible task? Looking back behaviour may be over-interpreted."**
- Source read: Europe PMC abstract (PMID 32090291).
- Design: modified impossible task with three possible and one impossible trial, four conditions (social, asocial, dummy human, object); 20 pet dogs (homes) vs 31 free-ranging dogs (Morocco).
- Results: both groups had similar persistence; looked back "with similar latencies at the human, dummy human, and object"; pet dogs looked longer at humans. Conclusion: "looking back in an impossible task does not represent a problem-solving strategy" per se; it relates to persistence, stimulus salience and reinforcement history.
- Assessment: important counter-evidence. For a robot it means: (i) looking back should be *learned from reinforcement history* (owner helped in the past -> look sooner/longer), and (ii) evaluation must not assume the observer reads look-back as "help seeking" unless the context is set up.

**A1.5 Hirschi, Mazzini, Riemer 2022, Animal Cognition. "Disentangling help-seeking and giving up: differential human-directed gazing by dogs in a modified unsolvable task paradigm."**
- Source read: PMC full text (https://pmc.ncbi.nlm.nih.gov/articles/PMC8753593/).
- Design: N=56 dogs (29 herding, 27 terriers). Two conditions: preferred toy locked in box with food puzzle freely available; or food locked in box with toy freely available. Logic: if gazing correlates positively with persistence it is help-seeking, if negatively it is giving up.
- Numbers: with alternative food still available, box interaction and gazing correlated positively (rs=0.51, p<0.0001); over the full 3-min period (after food consumed) the correlation was negative (rs=-0.42, p=0.001); box-related gazing in "food in box" condition rs=0.55. Gaze direction: when the owner was responsible for the box, 89-96% of gazes went to the owner; when the experimenter was responsible, 48-70% of box-related gazes went to the experimenter.
- Conclusion: "Dogs use gazing at humans' faces as a social problem-solving strategy, but not all gazing can be classified as such."
- Assessment: LOAD-BEARING together with A1.3. Gives the two-regime model the robot should reproduce: gaze *to the person who can help*, and gaze that co-occurs with continued trying (help request) vs gaze after abandoning (giving up). Also gives the evaluation metric: proportion of gazes directed at the responsible person (89-96% in dogs).

### A2. Social referencing (checking the owner's reaction to something ambiguous)

**A2.1 Merola, Prato-Previde, Marshall-Pescini 2012, PLoS ONE 7(10):e47653. "Dogs' Social Referencing towards Owners and Strangers."**
- Source read: PLoS full text (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0047653).
- Design: 90 dogs recruited (mean age 4.7 y); 57 analysed (29 owner-informant, 28 stranger-informant); a slightly scary object (electric fan with green ribbons); informant gives a positive or negative facial/vocal message.
- Numbers: referential looking (look at fan then at informant) 76% (22/29) with owner, 60% (17/28) with stranger (n.s., p=0.22); gaze alternation 62% vs 52%. With the owner as informant, positive-message dogs looked at the owner more (p=0.01), approached the fan faster (28.84 s vs 54.21 s, p=0.001) and touched it sooner (35.1 s vs 55.44 s, p=0.002); negative-message dogs stayed farther away. With a stranger, behavioural regulation was weak, and dogs looked more at the (seated) owner under negative messages.
- Assessment: LOAD-BEARING for the "state of the world" learning goal: the dog's approach/avoid decision toward a novel stimulus is *conditioned on the owner's affect*, and it is the owner, not any human, who carries the weight. For Parcel: CHECK_IN behavior = look at novel thing -> look at owner -> read owner valence (from voice/face) -> approach latency scales with owner valence.

### A3. Play signals: play bow, attention-getters, human play signals

**A3.1 Bekoff 1995, Behaviour 132:419-429. "Play signals as punctuation: the structure of social play in canids."**
- Source read: abstract page at the Animal Studies Repository (https://www.wellbeingintlstudiesrepository.org/acwp_ena/30/); the PDF returned 403 and Semantic Scholar had no abstract.
- Claim (verbatim from the abstract): "The non-random occurrence of bows supports the hypothesis that bows are used to maintain social play in these canids when actions borrowed from other contexts, especially biting accompanied by rapid side-to-side shaking of the head, are likely to be misinterpreted." Species: adult and infant domestic dogs, infant wolves, infant coyotes.
- Numbers: not retrievable from the abstract. Treat bow-timing percentages as unverified.

**A3.2 Byosiere, Espinosa, Marshall-Pescini, Smuts, Range 2016, PLoS ONE 11(12):e0168570. "Investigating the function of play bows in dog and wolf puppies."**
- Source read: PLoS full text (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0168570).
- Numbers: 10 dog puppies (2-5 months) and 15 wolf puppies (2.7-7.8 months); 136 dog bows and 69 wolf bows analysed. 135/136 dog bows (99%) and 69/69 wolf bows occurred when partners could see each other (visual-signal hypothesis supported). In dog puppies, both bower and partner showed more pause behaviours before bows than after (re-initiation function), replicating adult dogs; in wolf puppies bows did not re-start partner play. Bite behaviours near bows were only 13.6% (dogs) and 10.1% (wolves), so the "misinterpretable-behaviour" hypothesis was not supported in this dataset. Bowers did not perform more offensive behaviours after bows.
- Assessment: LOAD-BEARING for the PLAY_BOW trigger: bows are sent *only when the partner can see*, and their main function is to *restart play after a pause*. The robot should bow when (a) play had been happening, (b) there is a lull, and (c) the owner is facing it.

**A3.3 Horowitz 2009, Animal Cognition 12:107-118. "Attention to attention in domestic dog dyadic play."**
- Source read: Europe PMC abstract (PMID 18679727).
- Claim (abstract): "Play signals were sent nearly exclusively to forward-facing conspecifics; attention-getting behaviors were used most often when a playmate was facing away, and before signaling an interest to play. ... stronger attention-getters were used when a playmate was looking away or distracted, less forceful ones when the partner was facing forward or laterally."
- Assessment: LOAD-BEARING for the attention-getting ladder: choose the attention-getter's intensity from the owner's attentional state (face orientation, engagement with phone/screen, etc.). This is a natural, small, learnable policy (state = owner attention estimate; action = attention-getter level; reward = owner turns toward the dog).

**A3.4 Rooney, Bradshaw, Robinson 2001, Animal Behaviour 61:715-722. "Do dogs respond to play signals given by humans?"**
- Sources: OpenAlex record (DOI 10.1006/anbe.2000.1661, 110 citations; no abstract text available). Numbers quoted secondarily by Simonet et al. 2005 (A4.1): whispering alone elicited play with a 56% success rate, and combining it with a play bow "augmented" success significantly.
- Assessment: secondary only. Use as a hint that human whisper-like breathy sounds and human play bows are the two signals to detect as PLAY_INVITATION from the owner.

### A4. The "dog-laugh" (play pant)

**A4.1 Simonet, Versteeg, Storie 2005, Proc. 7th International Conference on Environmental Enrichment. "Dog-laughter: Recorded playback reduces stress related behavior in shelter dogs."**
- Source read: full PDF (https://www.laughing-dog.petalk.org/LaughingDog.pdf).
- Definition: during play dogs vocalize with "at least four distinct patterns; barks, growls, whines, and a breathy pronounced forced exhalation (dog-laugh)". Only the laugh "appears to be exclusively produced during play and friendly greetings". "Upon hearing a dog-laugh subjects use a play-face and chase or play-bow with the individual producing the dog-laugh, whether the individual is dog or human." Dogs also produce it during solitary object play.
- Design: SCRAPS shelter, Spokane; 120 dogs (4 months to 10 years); six Sundays; within-subject cross-over (baseline vs playback); 40-minute observation periods, each dog observed 3 min per pass, three passes, three observers; two blind coders; 22-code ethogram (Table 1: approach front of kennel, ran to back, play-bow, play-face, paws at door, sits, lies down, tail wag medium/fast, orients to recording/experimenter/away, shakes, lunges, bites door, growl, dog-laugh, whine, bark, explore kennel, urinate, defecate).
- Numbers: kennel ambient 74 dB (fans only); playback level 84 dB; peak noise fell from 120 dB (baseline) to 96 dB (playback). Significant baseline-vs-playback differences: social orienting to front of kennel t=-7.41, p=.0123; silence t=-7.01, p=.0121; play-bow t=-7.31, p=.0123; dog-laugh t=-7.11, p=.013; play-face t=-7.41, p=.0123. Puppies (4-12 months) answered with play-bows and dog-laughs; dogs 1-2 years oriented silently with medium-height, medium-pace tail wag; dogs over 2 years oriented and sat or lay down.
- Assessment: canonical but a conference proceeding, not peer reviewed in a journal. The spectrograms (Appendix A) show ~3 amplitude bursts within 1 s. This is the primary description of what a "chuckle" should *sound like* for Parcel: a breathy forced exhalation, no voicing, bursty envelope.

**A4.2 Volsche, Gunnip, Brown, Kiperash, Root-Gutteridge, Horowitz 2023, International Journal of Comparative Psychology 35. "Dogs produce distinctive play pants: Confirming Simonet." DOI 10.46867/ijcp.2023.35.5620, CC BY 4.0.**
- Source read: full PDF via eScholarship (https://escholarship.org/content/qt8t78q9xk/qt8t78q9xk.pdf).
- Design: 16 dog-human dyads (N=14 viable recordings); training (about 2 min), play (5-10 min), shared rest (5 min), always in that order; wireless mics on both partners.
- Operational definition of the play pant: frequencies 0-4 kHz; length 0.1-0.3 s; large irregular oscillating waveform, high amplitude; no harmonic bands. Resting pant after play: steady respiratory rhythm, lower amplitude, no bursts.
- Numbers: inter-rater ICC alpha=0.967 (95% CI 0.942-0.983). Rater 1: 378 target vocalizations, 365 (96.6%) co-occurring with play behaviour; Rater 2: 327, 295 (90.2%); averaged 353 target vocalizations of which 330 co-occurred with play. One-way ANOVA across interaction types F(2,39)=5.897, p=.006; fewer play pants in training (p=.018) and rest (p=.013); training vs rest n.s. (p=.999). Correlation between number of play pants and number of play behaviours rs(42)=0.998. Of 353, only 23 occurred outside the play phase and only 3 were not linked to play, play activity or direct contact (tickling, cuddling).
- Assessment: LOAD-BEARING for the "learn to chuckle" target. The dog-laugh is a *play-context* and *affiliative-contact* signal, not a response to humour per se. For Parcel, "chuckle when a joke was funny" should be modelled as: chuckle probability is high in a play/affiliative interaction frame with high arousal and positive valence; a joke is one route into that frame (via owner laughter/tone), and the learned part is *which owner cues predict that frame*.

### A5. Tail, face and body signals (emotion catalogs)

**A5.1 Quaranta, Siniscalchi, Vallortigara 2007, Current Biology 17:R199-R201. "Asymmetric tail-wagging responses by dogs to different emotive stimuli."**
- Sources: Europe PMC record (PMID 17371755; no abstract text) and OpenAlex record (DOI 10.1016/j.cub.2007.02.008, 284 citations). Content read via the summary in Artelle et al. 2010 (A5.2): dogs showed "a left-biased wag towards an unfamiliar conspecific or neutral stimulus, and a right-biased wag of varying amplitudes for heterospecific stimuli (an owner, an unfamiliar human, and a cat)".
- Assessment: primary numbers not retrieved; the qualitative direction (right-biased wag = approach/positive; left-biased = withdrawal/negative) is solid across A5.2 and A5.3.

**A5.2 Artelle, Dumoulin, Reimchen 2010, Laterality (iFirst, DOI 10.1080/13576500903386700). "Behavioural responses of dogs to asymmetrical tail wagging of a robotic dog replica."**
- Source read: full PDF (https://web.uvic.ca/~reimlab/robodogasym.pdf).
- Design: life-size Labrador-like robotic model; tail servo under a Parallax Stamp microcontroller; amplitude 0-45 deg, frequency 2.5 Hz, left- or right-biased wag; free-ranging dogs in a park approaching the model, filmed from ~15 m.
- Numbers: 2008: 80 interactions, 76 dogs, 74 trials analysed: with a left wag 56% of dogs approached continuously without stopping vs 31% with a right wag (chi-square 4.66, p=.031). 2009 replication: 198 left-wag and 180 right-wag trials, 37.4% vs 27.8% continuous (chi-square 3.94, p=.047); excluding trials with owners/other dogs present: 129 vs 107 trials, 41.1% vs 28.0% (chi-square 4.37, p=.037). Same trend in small, medium, large dogs. 15% of dogs barked at the model, no left/right difference. "Over 450 separate interactions".
- Assessment: a robot-dog experiment that shows *conspecific receivers respond to a single lateralized parameter of a tail wag*. Directly relevant: even one expressive DOF (wag bias) changes how an observer approaches. Note the direction surprised the authors (dogs paused more for the right wag); they interpret the stop as a cautious approach.

**A5.3 Siniscalchi, Lusito, Vallortigara, Quaranta 2013, Current Biology. "Seeing left- or right-asymmetric tail wagging produces different emotional responses in dogs."**
- Source read: Europe PMC abstract (PMID 24184108).
- Claim: dogs watching video of conspecifics "showed higher cardiac activity and higher scores of anxious behavior when observing left- rather than right-biased tail wagging."

**A5.4 Waller, Peirce, Caeiro, Scheider, Burrows, McCune, Kaminski 2013, PLoS ONE 8(12):e82686. "Paedomorphic facial expressions give dogs a selective advantage."**
- Source read: PLoS full text (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0082686).
- Design: 27 bull-breed shelter dogs (7-96 months, mean 29.46) at four UK shelters; 2-min filmed encounter; full DogFACS coding.
- Numbers: AU101 (inner brow raiser) frequency predicted rehoming speed, power-curve R^2=0.39: 5 AU101 movements -> about 49.83 days, 10 -> 34.88 days, 15 -> 28.31 days. Longer tail-wagging durations were associated with *longer* time to rehoming.
- Assessment: for a face-less quadruped this is mostly a caution: the strongest human-appeal signal in dogs is facial (paedomorphic "puppy eyes"); Parcel cannot produce it, so appeal must come from timing, posture and gaze proxies. The tail-wag result is also a warning that "more wagging" is not automatically "more likeable".

**A5.5 Kaminski, Hynds, Morris, Waller 2017, Scientific Reports 7:12914. "Human attention affects facial expressions in domestic dogs."**
- Source read: Europe PMC abstract (PMID 29051517).
- Claim: dogs "produced significantly more facial movements when the human was attentive than when she was not"; food (arousing, non-social) had no effect. Facial expressions are "potentially active attempts to communicate".
- Assessment: another audience-effect result (with A3.3): expressive output should be gated by the owner's attention, not emitted into the void.

**A5.6 Wan, Bolger, Champagne 2012, PLoS ONE 7(12):e51775. "Human perception of fear in dogs varies according to experience with dogs."**
- Source read: PLoS full text (https://journals.plos.org/plosone/article?id=10.1371/journal.pone.0051775) plus OpenAlex abstract.
- Design: 2,163 online participants (7% low-experience, 68% owners, 14% professionals <10 y, 11% professionals 10+ y); 9 videos (5 happy, 4 fearful) pre-classified by experts.
- Numbers: probability of labelling a fearful clip "fearful" ranged from .30 (low experience) to >.70 (professionals); happy clips .90-.93 regardless of experience. Professionals reported using ears far more (about 80% vs about 40% in the low-experience group for fearful clips); experienced viewers used about one more body feature (of five: ears, eyes, mouth/tongue, tail, legs/paws).
- Assessment: LOAD-BEARING for evaluation design. Naive viewers reliably read *happy* dog body language but not *fear*; and ears carry most of the expert signal. A Go2 has no ears, so negative/fearful states must be carried by whole-body cues (crouch, retreat, lowered height) and will be under-read by naive raters. Recruit raters with dog experience for fear/appeasement believability, or accept that only positive states will be evaluated well by the general public.

**A5.7 C-BARQ: Hsu & Serpell 2003, JAVMA 223:1293-1300, and the C-BARQ site.**
- Sources read: Europe PMC abstract (PMID 14621216); https://vetapps.vet.upenn.edu/cbarq/about.cfm.
- Numbers: development sample 1,851 dogs plus 203 clinical cases; 152-item questionnaire reduced by factor analysis to 68 items in 11 factors explaining 57% of variance. Current site: 14 behavioural categories (stranger-directed aggression, owner-directed aggression, dog-directed aggression, dog rivalry, stranger-directed fear, nonsocial fear, dog-directed fear, separation-related behaviour, attachment/attention-seeking, trainability, chasing, excitability, touch sensitivity, energy level) plus 22 miscellaneous items; database about 50,000 pet dogs of 300+ breeds and 35,000+ assistance-dog assessments.
- Assessment: C-BARQ is an owner-report *temperament* instrument, not an ethogram. Its value for Parcel is as a personality-parameter vocabulary (excitability, attachment/attention-seeking, nonsocial fear, energy) that can be exposed as tunable drives; it is not a behaviour list.

### A6. Attachment and greeting

**A6.1 Topal, Miklosi, Csanyi, Doka 1998, Journal of Comparative Psychology 112:219-229. "Attachment behavior in dogs: a new application of Ainsworth's Strange Situation Test."**
- Source read: Europe PMC abstract (PMID 9770312).
- Numbers: 51 owner-dog pairs; factor analysis gave three dimensions (Anxiety, Acceptance, Attachment); cluster analysis gave 5 classes; dogs could be placed on the secure/insecure axis; no effect of gender, age, living conditions or breed on most variables.
- Assessment: the Strange Situation is an off-the-shelf *evaluation protocol* for a companion robot: owner leaves / stranger enters / owner returns; score proximity-seeking, greeting, exploration in the owner's presence vs absence.

**A6.2 Rehn, Handlin, Uvnas-Moberg, Keeling 2014, Physiology & Behavior. "Dogs' endocrine and behavioural responses at reunion are affected by how the human initiates contact."**
- Source read: Europe PMC abstract (PMID 24471179).
- Numbers/claims: 12 female beagles; three reunion treatments: physical+verbal (PV), verbal only (V), no contact (C). In PV, "elevated levels of oxytocin were observed even after the interaction had ended" and cortisol decreased most; dogs in PV "initiated more physical contact ... and expressed more lip licking upon reunion"; in V "initial responses to reunion ... were tail wagging and vocalisations". Conclusion: physical contact was necessary for the sustained oxytocin rise.
- Rehn & Keeling 2011 (Applied Animal Behaviour Science, DOI 10.1016/j.applanim.2010.11.015, 113 citations per OpenAlex) is the paper on greeting intensity vs time left alone (0.5 h / 2 h / 4 h); its abstract could not be retrieved from any open endpoint this session (OpenAlex abstract null, ScienceDirect 403, SLU page moved). Do not cite its numbers without reading it.
- Assessment: greeting is the highest-value "state of the world" behaviour after look-back: it depends on absence duration (owner history), who is returning (owner model), and the owner's own greeting style (touch vs voice).

---

## Part B. Robot-pet ethograms and affect architectures

### B1. Sony AIBO (2003) and aibo ERS-1000 (current)

**B1.1 Arkin, Fujita, Takagi, Hasegawa 2003, Robotics and Autonomous Systems 42:191-201. "An ethological and emotional basis for human-robot interaction."**
- Source read: full PDF (https://sites.cc.gatech.edu/ai/robot-lab/online-publications/sony-iros.pdf); OpenAlex record shows 282 citations.
- Ethogram: adopted from Scott and Fox. Table 1 "Main Behavioral Subsystems of the Dog": Investigative (searching/seeking), Epimeletic (care and attention giving), Et-epimeletic (attention getting or care soliciting), Allelomimetic (doing what others in the group do), Agonistic (conflict), Sexual, Eliminative, Ingestive, Comfort-seeking (shelter-seeking), Miscellaneous Motor, Play, Maladaptive. Organised with Timberlake's behavioural-systems approach into subsystems, modes, modules. Agonistic modes: Fighting-Predation, Defense-Escape, Dominant Attitude, Subordinate Attitude. Defense-Escape modules: Sitting, Crouching, Running away, Yelping, Tail between legs, Defensive rolling on back, Move away from threat, Seek out human, Hair raising. Example rule (Figure 5): stimulus = threat or dominant animal present + attack + escape route present + high fear; response = run(fast, towards escape route) + ear-position(both, back).
- Motivation/emotion: "homeostasis regulation rule" for action selection; Ekman's 6 basic emotions placed in Takanishi's 3-D space (pleasant, arousal, confidence); pleasantness high when internal variables are within range; arousal driven by circadian rhythm and unexpected stimuli; confidence by recognition certainty. Implemented AIBO version: 6 internal variables (nourishment, moisture, bladder distension, tiredness, curiosity, affection) with 6 instinct variables (hunger, thirst, elimination, tiredness, curiosity, affection); Releasing Mechanism RM[I] x Motivation Mot[I] -> behaviour value V[I]; lateral inhibition against dithering; three implemented subsystems (investigative, ingestive, play), where play means "interactive behaviors with a human such as giving/offering its paw". Only 3 objects detectable by the colour camera at the time. Also proposes "emotionally grounded symbols" (EGO architecture): associate an object with the behaviour that changed internal variables.
- Assessment: LOAD-BEARING as the reference architecture for "state of the world -> behaviour": drives (homeostatic) + emotion (3-D) + releasers (perception) -> lateral-inhibition selection over an ethogram tree. This is what Parcel's reaction arbiter should grow into, with the *thresholds and releaser weights learned* instead of hand-set.

**B1.2 Fujita 2004, Proceedings of the IEEE 92(11). "On activating human communications with pet-type robot AIBO."**
- Source read: OpenAlex abstract (DOI 10.1109/jproc.2004.835364, 204 citations). Content: design concept "based on how to increase its 'lifelike' appearance"; marketing statistics and HRI experiments showing that AIBO "activates human emotions effectively" and "helps in human-human communication".

**B1.3 Sony aibo (ERS-1000) Help Guide, pages "aibo's desires and emotions", "Getting to know aibo", "aibo's growth and change", "Examples of the phrases that aibo can understand".**
- Sources read: https://helpguide.sony.net/aibo/ers1000/v1/en/contents/TP0001970094.html, .../TP0001970093.html, .../TP0001970095.html, .../TP0001970101.html.
- Desires (Sony's names): "Desire for your affection" (approach owner, attempt play, whimper when alone), "Curiosity" (approach strangers to memorise faces, attention-seeking, wander the territory), "Desire for sleep", "Desire to show feelings" (when high, "easily excited and increasingly does tricks that let you know how it really feels"). Emotions: "delight, anger, sorrow and pleasure"; delight when doing preferred activities/complimented; sadness "when there is no one to play with"; surprise "when it hears a loud sound". Expressed "through eye or tail movement or its tricks"; elsewhere "body language (eye, ear, tail movement) and voice tones". Growth: "about 3 years for aibo to reach the maturity stage from the infancy stage"; praise and scolding shape development; "the pattern of tricks and the strength of desires change".
- Voice-triggered tricks documented: Hand/Shake hands; Sit down; Lay down; Let's dance; Learn this / Remember this (learning posture); You got it / Show it to me; Don't forget; Show me your new trick; Stop / Never mind; Show me your face (turn and bark); Come on / Come to me (walk toward speaker); Take a picture / photo of everyone / one more; Charging station / Go to your mat; Pass me the bone / Bring me the bone; Kick the ball; Look for the ball. Praise phrases (Good boy/girl, Nice, Good job, I love you ...) -> positive reactions; scolding phrases (Bad boy, Don't do that, That's not right ...) -> sad reactions.
- Assessment: this is the only vendor-published behaviour list for a commercial robot dog I could read. Note the structure: a small set of *drives*, four *emotions*, an autonomous *behaviour repertoire* (explore, memorise faces, approach, play, self-charge), and voice-triggered *tricks* that are gated by mood. Parcel's current fixed command list corresponds only to the last layer.

### B2. MiRo (Consequential Robotics / Sheffield)

**B2.1 Mitchinson & Prescott 2016, Living Machines 2016, LNCS 9793. "MIRO: a robot 'mammal' with a biomimetic brain-based control system."**
- Source read: preprint PDF (https://eprints.whiterose.ac.uk/id/eprint/107017/1/MIRO-preprint.pdf).
- Hardware: differential-drive base; 3-DOF neck (lift, pitch, yaw); 2 DOF per ear (curl, rotate); 2 DOF tail (droop, wag); 1 DOF eyelids; stereo cameras, stereo mics in the ears, sonar in the nose, 4 body + 4 head capacitive touch sensors, 4 light sensors, 2 cliff sensors, accelerometers in head and body; two coloured light arrays; sound output.
- Architecture: three processors P1 "spinal cord" (ARM Cortex M0, reflexes), P2 "brainstem" (Cortex M0/M4), P3 "forebrain" (Cortex A8). Latency continuum: P1 ~10 ms, P2 ~30 ms, P3 ~50-200 ms, P4 (off-board) 100 ms+.
- Affect: circumplex (valence x arousal). "Stroking MIRO drives valence upwards, whilst striking him on the head drives valence down." Baseline arousal from real-time clock (circadian: more active in daylight), ambient sound and light; "very loud sound events raise arousal and decrease valence". Expression: "social pattern generators" drive lights, ears, tail, eyelids; vocalisation model modulated by affect ("morose to manic"); "low/high arousal slows/speeds movement, and very low arousal leads to a less upright posture of the neck."
- Spatial behaviour: salience map from visual change and a Jeffress sound-localisation model; plans "orient", "avert", "approach", "flee" with scalar priorities; a basal-ganglia model selects "with persistence and pre-emption"; a motor pattern generator moves a "generalised sensory fovea" in front of the nose ("led by the nose").
- Assessment: LOAD-BEARING as the second reference architecture. Two ideas transfer directly to a Go2 with no neck: (1) affect -> global motion *speed and posture height* modulation (arousal scales velocity; low arousal lowers the body), (2) a salience-map -> orient/avert/approach/flee plan set selected by a BG-like arbiter with persistence. Both are compatible with Parcel's 50 Hz body-intent lane.

### B3. Recent quadruped-specific perception studies (2023-2026)

**B3.1 Lakatos et al. 2025, Biologia Futura. "Does a 'robot dog' need legs, ears, and tail? A comparative analysis of intention- and emotion-attribution to Miro-E and Unitree Go1."**
- Source read: Europe PMC abstract (PMID 40461921); Crossref record (DOI 10.1007/s42977-025-00263-5, University of Hertfordshire).
- Numbers: 111 primary-school children aged 7-10 watched both robots in identical scenarios. Miro-E "better expressed emotions due to features like ears and tails"; no significant difference in intention attribution; children preferred Unitree Go1 overall. Both robots "effectively communicated intended emotions and intentions", supporting the "ethorobotics approach".
- Assessment: LOAD-BEARING for Parcel's platform choice: a Go1-class Unitree body without ears/tail can carry *intention* as well as a zoomorphic robot, and is preferred; it is weaker on *emotion*. So invest in intention-readability (anticipation, gaze proxies, approach/retreat) and accept/compensate on emotion (sound, lights, whole-body posture).

**B3.2 Yang, Biernacka, Bruno 2025, IEEE RO-MAN 2025. "Conveying emotion and intention through quadruped robotic motion: a validation study using canine-inspired movements."**
- Source read: OpenAlex abstract (DOI 10.1109/ro-man63969.2025.11217857; KIT SARAI lab).
- Numbers: 35 participants; canine-inspired designed movements; "movements to alert, neutral, yes/agree exceeded the average human recognition rate for robotic emotional expressions through body gestures"; prior experience with robots and dogs had no significant effect on recognition.
- Assessment: small N, but the first RO-MAN validation of canine-inspired quadruped motion; the recognisable set (alert, neutral, yes/agree) is intention-like rather than emotion-like, consistent with B3.1.

**B3.3 Gupta, Shin, Norman, Stephens, Lu, Sentis 2024, arXiv 2403.17270. "Human stress response and perceived safety during encounters with quadruped robots."**
- Source read: arXiv abstract. Boston Dynamics Spot and Unitree Go1 navigating autonomously among participants wearing ECG and EDA sensors; findings: elevated stress vs baseline, more stress with multiple robots, and "navigation behavior ... triggered higher stress than search behavior".
- Assessment: a quadruped moving purposefully *toward/through* people is stressful; the companion must telegraph intent (anticipation, slow-in) and keep approach behaviours readable. Physiological measures are a usable objective complement to questionnaires.

**B3.4 e-Inu (Chakravarty et al. 2023, arXiv 2301.00964).** Simulated quadruped with speech emotion recognition (63.5% accuracy) and video emotion recognition (99.66%), PPO gait. Read from the abstract only; low rigour, included only as a prior attempt at "emotion-sensing quadruped".

---

## Part C. Animation principles for robots

**C1. Ribeiro & Paiva 2019, arXiv 1904.02898. "Nutty-based Robot Animation: Principles and Practices" (extends Ribeiro & Paiva 2012, HRI, "The Illusion of Robotic Life").**
- Source read: full arXiv PDF (converted with pdftotext). The 2012 HRI paper itself exists in OpenAlex but no abstract was retrievable; the 2019 paper restates and extends it.
- Definition (quoting van Breemen): robot animation is "the process of computing how the robot should act such that it is believable and interactive"; the authors add "the workflow and processes that give a robot the ability of expressing identity, emotion and intention during autonomous interaction with human users".
- The 12 Principles of Robot Animation (section 3, demonstrated on NAO and EMYS): 3.1 Squash and Stretch (via poses/body movement when the hardware cannot deform); 3.2 Anticipation (a short opposite movement, e.g. 10 deg back before a 90 deg turn); 3.3 Intention (renamed Staging: show the target of the next action by facing it, use light/sound to direct attention); 3.4 Animated, Procedural and Ad-hoc Action (from Straight-Ahead/Pose-to-Pose; trade-off expressivity vs responsiveness); 3.5 Slow In and Slow Out (van Breemen's "Merging Logic"; or feed-forward velocity/acceleration/jerk saturation filter for ad-hoc motion); 3.6 Arcs (head turns include vertical component); 3.7 Exaggeration (contrast the motion signal); 3.8 Secondary Action and Idle Behavior (keep-alive: blinking, "soft, sinusoidal motion to the body to simulate breathing"); 3.9 Asymmetry (from Solid Drawing: never stand stiff or symmetric; weight shifting; symmetry only to convey stiffness); 3.10 Expectation (from Appeal: motion style must match the character's intended role); 3.11 Timing ("correlation between acceleration and perceived arousal"; faster = engaged); 3.12 Follow-Through and Overlapping Action (use with caution on robots: safety, balance; useful to mark the end of an action in pre-animated motion).
- Assessment: LOAD-BEARING as the design vocabulary for Parcel's expression layer. Parcel already has idle breathing and nods; the missing principles with the biggest expected payoff on a quadruped are Anticipation, Intention (face the target before moving), Asymmetry, Timing-as-arousal, and Slow In/Out filtering on the 50 Hz body-intent lane.

**C2. Takayama, Dooley, Ju 2011, HRI 2011. "Expressing thought: improving robot readability with animation principles."**
- Source read: prepress PDF (https://www.leilatakayama.org/downloads/Takayama.Animation_HRI2011_prepress.pdf).
- Design: online video-prototype experiment, N=273 adults; 2 (forethought vs none, between) x 2 (goal-oriented reaction vs none) x success/failure; PR2 animations of four tasks (opening door, requesting power, delivering drink, ushering); readability measured by open-ended description keyword match and by viewer sureness (7-point); adjectives: appealing, approachable, competent, confident, intelligent, ...; Bonferroni .05/7.
- Numbers: forethought did not change keyword-match readability (F(1,271)=0.65, p=.42); keyword match differed by task (opening door M=0.84, requesting power 0.78, delivering drink 0.64, ushering 0.29; F(3,813)=95.29). Forethought increased viewer sureness (M=5.69 vs 5.20; F(1,255)=15.95, p<.00001), appeal (4.83 vs 4.27; F(1,265)=16.51, p<.0001) and approachability (5.05 vs 4.54; F(1,262)=12.48, p<.0001). Showing a reaction increased perceived confidence (4.53 vs 4.14; F(1,267)=7.51, p<.007). Competence-intelligence (r=.83 between the two items) was higher after success (4.68) than failure (3.86).
- Assessment: LOAD-BEARING evidence that *anticipation before action* and *reaction after outcome* improve appeal/approachability/confidence even when they do not improve literal comprehension. For Parcel: every learned behaviour should be emitted as [anticipation micro-move] -> [action] -> [reaction to outcome]. The "look back when lost" behaviour is itself a reaction-to-failure display.

**C3. Schulz, Torresen, Herstad 2019, ACM THRI 8(2). "Animation Techniques in Human-Robot Interaction User Studies: A Systematic Literature Review."**
- Source read: Semantic Scholar abstract (DOI 10.1145/3317325; 53 citations). 27 articles reviewed; animation-based movement "improving individual perceptions of robot qualities, clarifying robot intentions, and conveying robot states or emotions", effective "even for robots lacking humanoid ... appearance"; calls for longitudinal studies.

**C4. Hielscher, Bulling, Arras 2025, IROS 2025, arXiv 2504.06735. "Interactive Expressive Motion Generation Using Dynamic Movement Primitives."**
- Source read: arXiv HTML. Eight principles implemented as parametric DMP modulations: Arc (Gaussian filtering / unsharp masking), Anticipation (inverted acceleration at start), Slow In/Out (sigmoid phase), Timing (duration scaling), Exaggeration (forcing-term amplitude), Secondary Action, Follow Through, Randomization. Six expressions (Joy, Sadness, Anger, Fear, Shame, Hurry) built by tuning principle intensities; platforms KUKA iiwa (sim), Pepper (17 DoF), Daryl (10 DoF). User study N=34 (ages 20-60): intended expressions recognised above chance (p<.05); high vs low intensity modulations perceived correctly for all principles (p<.05).
- Assessment: a concrete, training-free way to implement C1's principles as *continuous parameters* on top of any trajectory (including Go2 velocity/pose intents). The parameter vector (anticipation, slow-in/out, timing, exaggeration, randomization) is a natural low-dimensional "style" action space for a learned policy.

**C5. Disney Research: Grandia et al. 2025, RSS 2024 / arXiv 2501.05204. "Design and Control of a Bipedal Robotic Character."**
- Source read: arXiv HTML. Robot: 5 DoF per leg + 4 DoF neck/head (14 actuated) + 2 DoF antennas, illuminated eyes, speakers; 15.4 kg, 0.66 m. Animation engine composes three layers (background animation, triggered animations, joystick-derived) and three motion classes: perpetual (balance), periodic (walking, phase-cycled), episodic (fixed-duration dances/jumps, monotonic phase). RL: PPO in Isaac Gym with actuator models, 8192 environments x 24 steps per batch, 100,000 iterations (about 22 days on an RTX 4090), 50 Hz policy, 600 Hz actuator bus; reward: torso pose tracking, joint tracking (legs weight 15, neck 100), contact matching, torque/smoothness penalties, survival bonus 20. Results: standing MAE 0.035 rad, walking 0.123 rad, episodic 0.027-0.043 rad; walks 0.7 m/s forward, 0.4 m/s lateral, 1.8 rad/s turn. Disney Research + Walt Disney Imagineering R&D.
- Assessment: LOAD-BEARING as the state-of-the-art recipe for "artist-directed expressive motion + robust RL tracking": the *animation engine* decides what to express (blending perpetual/periodic/episodic clips), and the *RL tracker* makes it physically robust. For Parcel, the split maps onto: behaviour catalog + expression layer (animation engine) over Go2 sport-mode / a future RL tracker.

**C6. Watanabe, Li, Hutter 2025, ICRA 2025, arXiv 2502.10980. "DFM: Deep Fourier Mimic for Expressive Dance Motion Learning."**
- Source read: arXiv HTML. Robot: Sony aibo, 14 DoF (12 leg + 2 head). Data: 170 clips = 34 artist-made dance motions x 5 speed variants (0.5-1.5x), 6 s each. Fourier Latent Dynamics (PAE-based) with forward-prediction horizon reduced to N=0. PPO in Isaac Gym, 3x256 MLP, 400 Hz sim / 100 Hz control, 5,000 iterations. Tracking MAE 0.094 rad (vs 0.132 for the FLD baseline); 0.5 s transitions; runs on aibo hardware while also doing locomotion and gaze control.
- Assessment: proof that an *expressive clip library on a consumer robot dog* can be turned into a single RL policy that blends clips and still does base activities. Dataset is Sony-proprietary.

**C7. Heyrman, Li, Klemm, Kang, Coros, Hutter 2025, arXiv 2512.07673. "Multi-Domain Motion Embedding: Expressive Real-Time Mimicry for Legged Robots."**
- Source read: arXiv HTML. Platforms: ANYmal D (quadruped), Unitree H1 (sim), Fourier N1 (hardware). Animal data: about 10 minutes of dog mocap augmented to about 52 minutes; humans from AMASS. Embedding: 32-D variational latent + wavelet-entropy features (13 for quadruped, 7 for humanoid) + periodic conv channels (25/15). PPO in IsaacLab, 30,000 iterations (ANYmal), 24 steps/env, 50 Hz control; zero-shot hardware deployment; beat VMP and PAE baselines on reconstruction.
- Assessment: the closest open recipe for "dog motion -> quadruped in real time" (ETH). Whether code/weights are released was not stated in the HTML I read; treat as method-only until checked.

**C8. Kine2Go (Palucki, Siwak, Ciebiera, Cygan 2026, arXiv 2606.14433, University of Warsaw, CC BY 4.0).**
- Source read: arXiv HTML. 800 Unitree Go2 kinematic trajectories from 40 RL policies (20 rollouts each, 5-20 s), gaits: walk/trot/run/turn/spin/canter/pace/strafe, figure-eights, crawl (from Solo8), horse-derived trot/walk; 60 Hz control with 4x decimation; per-frame joint pos/vel, base quaternion/angular velocity, actions, global positions. Excludes jumping and sitting; flat terrain only.
- Assessment: a directly usable, openly licensed Go2 motion prior for locomotion *style*, not for the expressive episodic actions.

**C9. Marmpena, Garcia, Lim, Hemion, Wennekers 2022, arXiv 2205.00763. "Data-driven emotional body language generation for social robotics."**
- Source read: arXiv abstract. CVAE over hand-designed Pepper expressions, conditioned on valence/arousal via latent-space geometry; generated expressions "not perceived differently from the hand-designed ones" on anthropomorphism and animacy; conditioning distinguishable except neutral-vs-positive valence and low-vs-medium arousal.
- Assessment: a small-data generative route to *variation* in expressive clips (the Asymmetry/Randomization principle) without new authoring.

**C10. Cuan, Fisher, Okamura, Engbersen 2023, arXiv 2306.02632. "Music Mode."** Read from abstract: mapping joint motion to sound made robots rate as "more safe, animate, intelligent, anthropomorphic, and likable" (Godspeed), and movement-synchronised sound beat random sound on perceived intelligence; about 200 hours of real-world operation. Supports adding a *motion-synchronised audio channel* (breath/pant/chuckle) to a face-less quadruped.

---

## Part D. Evaluation instruments for believability / animacy / likeability

**D1. Godspeed Questionnaire Series. Bartneck, Kulic, Croft, Zoghbi 2009, Int J Social Robotics 1(1):71-81; Bartneck 2023 chapter "Godspeed Questionnaire Series: Translations and Usage" (Springer, DOI 10.1007/978-3-030-89738-3_24-1); Weiss & Bartneck 2015 RO-MAN meta-analysis.**
- Sources read: https://www.bartneck.de/publications/2009/measurementInstrumentsRobots/ ; the 2023 chapter PDF (https://www.bartneck.de/publications/2023/godspeed/bartneckGodspeedChapter2023.pdf, pdftotext); OpenAlex abstract of Weiss & Bartneck 2015 (DOI 10.1109/roman.2015.7333568).
- Items (5-point semantic differentials): Anthropomorphism: Fake/Natural, Machinelike/Humanlike, Unconscious/Conscious, Artificial/Lifelike, Moving rigidly/Moving elegantly. Animacy: Dead/Alive, Stagnant/Lively, Mechanical/Organic, Artificial/Lifelike, Inert/Interactive, Apathetic/Responsive. Likeability: Dislike/Like, Unfriendly/Friendly, Unkind/Kind, Unpleasant/Pleasant, Awful/Nice. Perceived Intelligence: Incompetent/Competent, Ignorant/Knowledgeable, Irresponsible/Responsible, Unintelligent/Intelligent, Foolish/Sensible. Perceived Safety (emotional state): Anxious/Relaxed, Agitated/Calm, Quiescent/Surprised.
- Reliability numbers (2023 chapter): original studies alpha 0.87-0.92 (anthropomorphism), 0.70 (animacy), 0.86-0.92 (likeability), 0.75-0.76 (perceived intelligence); Ho & MacDorman 2010: about 0.92 (likeability, anthropomorphism), about 0.88 (animacy, perceived intelligence), 0.6 (perceived safety, below the original about 0.75); Stroessner 2020 review: anthropomorphism 0.86-0.93, animacy 0.70-0.76, likeability 0.84-0.92, perceived intelligence 0.75-0.92, perceived safety 0.91. Usage: translated into 19 languages (16 collected as of 2022); 1,852 citations by 2022; the 2015 meta-analysis found that of 160 citing papers only 69 were empirical and only 21 used the same hardware, so cross-study comparison is hard; the meta-analysis itself qualitatively analysed 18 studies. Perceived safety correlates with physiological measures (Kulic & Croft).
- Assessment: LOAD-BEARING as the default instrument. Caveat from Hauser et al. 2023 (OpenAlex abstract, DOI 10.1145/3597512.3599707): in incidental encounters with autonomous quadrupeds (n=26 pilot, n=22 main), Godspeed differences were "largely statistically insignificant" although interviews showed clear effects; so pair Godspeed with behavioural/physiological measures and open-ended interviews.

**D2. RoSAS. Carpinella, Wyman, Perez, Stroessner 2017, HRI 2017 (682 citations per Semantic Scholar). Validation for physical HRI: Pan, Croft, Niemeyer 2017 (UBC/Disney Research).**
- Sources read: Semantic Scholar record (abstract elided); GMU HRI scale database page (items "not publicly available at this time"); UBC validation PDF (https://caris-mech.sites.olt.ubc.ca/files/2017/09/HRI-CME_2017_paper_5.pdf, pdftotext).
- Items (UBC Table I): Competence: Reliable, Competent, Knowledgeable, Interactive, Responsive, Capable. Warmth: Organic, Sociable, Emotional, Compassionate, Happy, Feeling. Discomfort: Awkward, Scary, Strange, Awful, Dangerous, Aggressive. Original validation used images of human/robot/blended faces; the UBC study (22 participants, KUKA iiwa handovers) confirmed internal consistency and unidimensionality of each attribute in a physical task.
- Assessment: RoSAS Warmth is the closest thing to "companion-ness"; Discomfort is the safety-perception counterpart for a 15 kg quadruped. Use both Godspeed and RoSAS (18 items) in short sessions.

**D3. Recent perception numbers for low-DoF expressive robots: Rogel, Yadollahi, Laban 2026, arXiv 2605.12786 (Reachy Mini).**
- Source read: arXiv HTML. 100 participants, within-subjects online, 10 clips (Joy, Amusement, Love, Pleasure, Interest; Shame, Fear, Disgust, Anger, Sadness) on a 6-DoF head + rotating base + antennae with non-verbal audio, gestures mapped with Laban Movement Analysis. Exact-label accuracy 30.5% overall: Anger 81.8%, Interest 62.2%, Sadness 55.0%, Amusement 43.4%, Fear 39.8%, Pleasure 3.1%, Shame 2.0%, Love 1.0%, Disgust 0%. Valence recovered 65.9%, arousal 67.8%. Used RoSAS warmth items + HRIES animacy; animacy "varied less across expressions" than warmth/sociability.
- Assessment: LOAD-BEARING calibration for what to expect: on a constrained body, *coarse* valence/arousal is readable (about two-thirds), exact emotion is not (about 30%). Parcel should target and measure valence/arousal readability, and only claim a few discrete states (alert, content, playful, fearful) that map onto distinct whole-body patterns.

**D4. Other evaluation anchors already covered:** Wan 2012 (A5.6, N=2,163: fear under-read by naive viewers); Takayama 2011 (C2, N=273); Lakatos 2025 (B3.1, N=111 children); Yang 2025 (B3.2, N=35); Hielscher 2025 (C4, N=34); Gupta 2024 (B3.3, ECG/EDA); Topal 1998 Strange Situation (A6.1) as a behavioural protocol; Simonet 2005 22-code shelter ethogram (A4.1) as a behavioural coding scheme.

---

## Part E. Unitree Go2 built-in expressive actions (what is actually documented)

- Sources read: `unitree_sdk2/include/unitree/robot/go2/sport/sport_client.hpp` (GitHub), `unitree_sdk2_python/unitree_sdk2py/go2/sport/sport_api.py` (raw), `unitree_sdk2_python/example/go2/high_level/go2_sport_client.py` (raw), `unitree_ros2/example/src/src/go2/go2_sport_client.cpp` (raw), and a DeepWiki page for the Python SDK. The official Unitree support pages ("High level Sports Service Interface", "AI sport control interface") are JavaScript-rendered and returned only a page title, so their prose descriptions could not be read.
- SportClient methods (header, no doc comments at all): Damp, BalanceStand, StopMove, StandUp, StandDown, RecoveryStand, Euler(roll,pitch,yaw), Move(vx,vy,vyaw), Sit, RiseSit, SpeedLevel, Hello, Stretch, Content, Dance1, Dance2, SwitchJoystick, Pose(bool), Scrape, FrontFlip, FrontJump, FrontPounce, Heart, StaticWalk, TrotRun, EconomicGait, LeftFlip, BackFlip, HandStand(bool), FreeWalk, FreeBound(bool), FreeJump(bool), FreeAvoid(bool), ClassicWalk(bool), WalkUpright(bool), CrossStep(bool), AutoRecoverSet/Get, SwitchAvoidMode. (The C++ header no longer lists WiggleHips, Wallow, BodyHeight, FootRaiseHeight, SwitchGait, Trigger, TrajectoryFollow, ContinuousGait; the Python sport_api.py IDs list below likewise lacks WiggleHips/Wallow. Parcel's `go2_sport_body_adapter.py` already names Sit and Stretch.)
- api_id constants (sport_api.py): DAMP 1001, BALANCESTAND 1002, STOPMOVE 1003, STANDUP 1004, STANDDOWN 1005, RECOVERYSTAND 1006, EULER 1007, MOVE 1008, SIT 1009, RISESIT 1010, SPEEDLEVEL 1015, HELLO 1016, STRETCH 1017, CONTENT 1020, DANCE1 1022, DANCE2 1023, SWITCHJOYSTICK 1027, POSE 1028, SCRAPE 1029, FRONTFLIP 1030, FRONTJUMP 1031, FRONTPOUNCE 1032, HEART 1036, STATICWALK 1061, TROTRUN 1062, ECONOMICGAIT 1063, LEFTFLIP 2041, BACKFLIP 2043, HANDSTAND 2044, FREEWALK 2045, FREEBOUND 2046, FREEJUMP 2047, FREEAVOID 2048, CLASSICWALK 2049, WALKUPRIGHT 2050, CROSSSTEP 2051, AUTORECOVERY_SET 2054, AUTORECOVERY_GET 2055, SWITCHAVOIDMODE 2058.
- Durations: NOT documented anywhere I could read. The Python example only sleeps 1 s between actions and 2-4 s between enabling/disabling the flag-type gaits (HandStand 4 s, FreeBound 2 s, FreeAvoid 2 s, WalkUpright 4 s, CrossStep 4 s, FreeJump 4 s); the ROS2 example uses dt=0.1 s and a one-shot flag for Sit/RiseSit. All calls except Move are synchronous RPCs (DeepWiki). The one-line descriptions on DeepWiki ("Wave greeting gesture", "Stretching routine", "Contentment gesture", "Heart-shaped gesture", "Scraping motion", "Pouncing motion forward", ...) are AI-generated and should not be cited as vendor documentation.
- What this means: the expressive actions are opaque, non-interruptible clips with unknown durations and no blending. Parcel must measure each action's duration and footprint on hardware (or in the Unitree MuJoCo model if it reproduces them, which is doubtful because they are firmware behaviours), and treat them as *episodic* animations in the Disney sense (C5) that the body-intent lane cannot modulate mid-clip. Continuous expression (posture height, speed, yaw/pitch via Euler, gait choice) is where learned modulation is possible today.

---

## Part F. What this means for Parcel

1. **Two of the owner's target behaviours have precise ethological definitions.**
   - *Look back when lost* = the unsolvable-task look-back: it is emitted when a persistence budget is exhausted (A1.3), it is directed at the person who can help (89-96% to the owner when the owner controls the resource, A1.5), it is sooner and longer when the human is a social partner and has helped before (A1.3, A1.4), and it co-occurs with continued trying when the dog is asking for help vs after abandoning when giving up (A1.5). Implementation: a learned persistence threshold per task type + owner-model "help history" term; output = stop, turn body toward owner (Go2 has no neck, so body yaw + Euler pitch is the gaze proxy), hold, optionally alternate gaze between obstacle and owner (gaze alternation, A2.1), wait for owner response, then either resume or approach. Reward signal: owner responds (speech/approach) within a window.
   - *Chuckle when a joke is funny* = the dog-laugh/play pant: a breathy forced exhalation, 0-4 kHz, 0.1-0.3 s bursts, no harmonics (A4.2), emitted almost exclusively in play and affiliative contact (93% co-occurrence with play behaviours; A4.2), and it *initiates* play in listeners (A4.1). Implementation: the audio primitive is fixed; the learned part is the trigger: P(chuckle | interaction frame is playful, arousal high, valence positive, owner attentive). Owner laughter, playful prosody, tickling/petting touch events and play invitations (human play bow, whisper) are the releasers; a joke is one path into that state via the conversation LLM's valence estimate. Evaluate by whether owners answer the chuckle with more play (Simonet's play-bow/play-face increase).

2. **Architecture: drives + affect + releasers -> arbiter over an ethogram, with learned thresholds.** Both AIBO (B1.1) and MiRo (B2.1) use homeostatic drives (affection, curiosity, tiredness), a 2-3-D affect space (valence, arousal, (confidence)), perception releasers, and lateral-inhibition / basal-ganglia selection over a behaviour tree. Parcel's reaction arbiter and owner model already hold the pieces; what is missing is (a) a persistent drive state updated by world events (stroke -> valence up; loud sound -> arousal up, valence down; owner absent long -> affection drive up), and (b) affect modulating *all* motion continuously (arousal scales speed and body height; B2.1) rather than selecting from a list.

3. **Audience gating.** Dogs send play signals and facial expressions only when the partner can see (A3.2 99% of bows with visual access; A5.5), and scale attention-getters to the partner's inattention (A3.3). Every expressive behaviour in the catalog should check "owner attention" first; this is a cheap, learnable policy with a clear reward (owner orients).

4. **Animation principles are the expression grammar.** Anticipation + reaction raise appeal/approachability/confidence (C2, N=273), and eight principles can be continuous DMP parameters (C4). Wrap every learned action in [anticipation] -> [action] -> [reaction], apply slow-in/out filtering on the body-intent lane, add asymmetry/randomization to idle, and use timing-as-arousal.

5. **Platform reality (Go2 without ears/tail/face).** Children read intention equally from a Unitree Go1 and a zoomorphic Miro-E but read emotion better from Miro-E (B3.1); naive adults read happy but not fearful dog body language and rely on ears (A5.6); low-DoF bodies convey valence/arousal (about 66-68%) far better than discrete emotions (about 30%) (D3). So: design and evaluate for *intention* and *valence/arousal*, use sound (pant, chuckle, whine) as the emotion channel, and do not expect discrete-emotion recognition above ~50% except for anger-like alert.

6. **Evaluation plan.** Per session: Godspeed (Animacy, Likeability, Perceived Safety) + RoSAS (18 items); valence/arousal 2-D ratings of clips (D3 style); behavioural protocol borrowed from the Strange Situation (A6.1: leave/return, stranger) with coded greeting intensity; help-seeking readability test = owner shown the "lost" episode and asked what the dog wants; play test = does the owner produce a play response within N seconds of a chuckle/bow (A4.1). Recruit dog-experienced raters for fear/appeasement items (A5.6). Add ECG/EDA if approach behaviours are tested at close range (B3.3).

7. **Training/simulation implications.** The episodic Go2 actions are opaque clips with undocumented durations (Part E); simulation can train the *selection/timing/style* policy (which behaviour, when, how fast, how high) but not the clip internals. The Disney split (animation engine that composes perpetual/periodic/episodic motion + RL tracker; C5) and the aibo/ANYmal clip-blending policies (C6, C7) are the paths to replacing sport-mode clips with a learned tracker later; Kine2Go (C8, CC BY 4.0) is an immediate Go2 locomotion-style prior.

---

## Part G. Proposed named behavior catalog (34 behaviors)

Notation: [trigger] -> behavior; (ethology source); {Go2 mapping today}. Affect state = (valence v, arousal a) plus drives (affection, curiosity, fatigue) and owner-attention estimate.

**Attention, contact and help-seeking**
1. LOOK_BACK: [task/nav failure after persistence budget; owner present] -> stop, yaw body to owner, slight pitch-up, hold 1-3 s (A1.3, A1.5) {StopMove; Move(0,0,vyaw); Euler pitch}
2. GAZE_ALTERNATE: [after LOOK_BACK, no owner response] -> alternate orientation obstacle <-> owner 2-3 times (A2.1 gaze alternation 62%) {Move yaw / Euler}
3. CHECK_IN (social referencing): [novel or ambiguous object/sound, owner present] -> orient to object, then to owner, wait for owner valence; approach latency scales with owner positivity (A2.1: 28.8 s vs 54.2 s) {Euler; Move}
4. ATTENTION_GETTER_SOFT: [owner facing away, low urgency] -> approach into view + small Hello (A3.3) {Move; Hello 1016}
5. ATTENTION_GETTER_STRONG: [owner distracted/looking away, higher drive] -> paw scrape + vocalization + closer approach (A3.3; AIBO et-epimeletic) {Scrape 1029; audio}
6. CONTACT_SOLICIT: [affection drive high, owner attentive] -> lean/nudge posture, lowered front (AIBO "Desire for your affection"; A6.2 contact) {Euler pitch; BodyHeight/low stance}
7. SEEK_OUT_HUMAN: [fear high + owner present] -> move to owner, lower body (Scott/Fox Defense-Escape module via B1.1) {Move; StandDown partial}

**Greeting and attachment**
8. GREET_OWNER: [owner returns after absence] -> approach fast, Hello, hip wiggle/body sway, vocalize; intensity scales with absence duration (A6.2; Rehn 2011 unread) {Move; Hello 1016; Euler roll oscillation}
9. GREET_STRANGER: [unfamiliar person enters] -> cautious orient, slow approach with stops, lower height (A5.2 cautious approach; B1.3 aibo memorises faces) {Move slow; Euler}
10. FOLLOW_PROXIMITY: [owner walking away, attachment drive] -> keep 1-2 m, glance back periodically (A6.1 proximity seeking) {Move}
11. SETTLE_NEAR_OWNER: [owner sits, arousal low] -> sit/lie within reach (A6.1; Simonet 2005 older dogs sit/lie) {Sit 1009; StandDown 1005}

**Play**
12. PLAY_BOW: [play frame active, lull in play, owner facing dog] -> front-down bow, hold, then bounce (A3.2 re-initiation; visibility) {Stretch 1017 as proxy; custom pose via Euler pitch + low front}
13. PLAY_INVITE: [owner play signal detected: human play bow, whisper/breathy voice, toy presented] -> PLAY_BOW + chuckle (A3.4 via A4.1; A4.1) {Stretch; audio}
14. CHUCKLE (play pant): [play frame, a high, v positive, owner attentive; or affiliative touch; or owner laughter/joke valence high] -> breathy 0-4 kHz bursts 0.1-0.3 s, 2-4 bursts (A4.1, A4.2) {audio only; optional body bob}
15. POUNCE: [play frame, toy/hand moving] -> FrontPounce (play chase) {FrontPounce 1032}
16. PLAY_JUMP: [play frame, arousal very high] -> FrontJump or FreeJump burst (AIBO/aibo play) {FrontJump 1031; FreeJump 2047}
17. ZOOMIES: [arousal very high, open space, owner attentive] -> short FreeBound loop (self-handicapping exaggerated play) {FreeBound 2046}
18. SELF_HANDICAP: [play with child/cautious owner] -> slower, exaggerated, lower-force play variants (Bekoff play structure; C1 Exaggeration) {SpeedLevel low}
19. CELEBRATE: [praise phrase, success] -> Dance1/Dance2 short (aibo "delight" on compliments) {Dance1 1022 / Dance2 1023}
20. AFFECTION_DISPLAY: ["I love you"/petting sustained, v high] -> Heart (aibo praise reactions) {Heart 1036}

**Affect displays (continuous and discrete)**
21. CONTENT: [v high, a low, after contact or food-equivalent] -> Content clip; slow breathing idle (B1.1 pleasantness in-range) {Content 1020}
22. WIGGLE (tail analog): [approach motivation, v high] -> hip/body sway, right-biased amplitude for approach contexts (A5.1, A5.2) {Euler roll/yaw oscillation; WiggleHips only if firmware exposes it}
23. ALERT: [novel loud sound / new person; a up] -> freeze, orient, raise body height (B2.1 loud sound -> arousal up; B3.2 "alert" recognised) {StopMove; BalanceStand; Euler}
24. STARTLE_RETREAT: [very loud sound, v down] -> back away 0.5-1 m, lower body, then CHECK_IN (B2.1; B1.1 Defense-Escape) {Move(-vx); StandDown partial}
25. CROUCH_APPEASE: [scolding phrase / owner anger prosody] -> lower body, slow, hold (aibo sad reactions to scolding; Defense-Escape crouching) {BodyHeight low; SpeedLevel low}
26. SAD_WITHDRAW: [no one to play with for long, affection drive unmet] -> slow, low posture, occasional look toward owner's last position (aibo sadness "when there is no one to play with") {StandDown; slow Euler}
27. SURPRISE_HOP: [unexpected pleasant event] -> small anticipation dip then hop (C1 Anticipation; aibo surprise) {FrontJump low / Euler}

**Rest, homeostasis and idle**
28. IDLE_BREATHE: [always, arousal-scaled] -> sinusoidal body bob with asymmetric weight shift (C1 Idle/Asymmetry) {Euler micro-oscillation; existing idle}
29. LOOK_AROUND: [curiosity drive, no salient stimulus] -> slow yaw scans with vertical arcs (C1 Arcs; MiRo orient) {Euler yaw/pitch; existing look_around}
30. EXPLORE_PATROL: [curiosity high, owner absent] -> wander known map, orient to changes (aibo territory learning; AIBO investigative) {FreeWalk / nav}
31. STRETCH_WAKE: [after rest, arousal rising] -> Stretch then shake-off sway (aibo life-support tricks; comfort subsystem) {Stretch 1017; Euler roll}
32. BODY_SHAKE: [after greeting or stress, displacement] -> fast roll oscillation 1 s (A6.2 reunion behaviours) {Euler roll}
33. SIT_SETTLE / LIE_REST: [fatigue drive, low arousal, circadian evening] -> Sit -> StandDown; Damp when "asleep" (B2.1 circadian; aibo desire for sleep) {Sit 1009; StandDown 1005; Damp 1001}
34. ANTICIPATE_THEN_REACT (meta-behavior): [any action] -> 100-300 ms opposite micro-move before, and a success/failure reaction after (C2; C1) {Euler micro-move; Content/Hello on success, CROUCH_APPEASE-lite or LOOK_BACK on failure}

Coverage check against the ethogram in B1.1: investigative (29, 30), et-epimeletic (4-7), epimeletic/affiliative (6, 8, 11, 20), allelomimetic (10), agonistic-defensive (23-25), comfort-seeking (31-33), play (12-19), affect expression (21-22, 26-27), plus the two owner targets (1, 14).

---

## Sources (all fetched this session)
- Miklosi et al. 2003 (Europe PMC, PMID 12725735)
- Marshall-Pescini et al. 2015 (PMC4614426)
- Marshall-Pescini et al. 2017 (Europe PMC 28422169; PMC5395970)
- Lazzaroni et al. 2020 (Europe PMC, PMID 32090291)
- Hirschi et al. 2022 (PMC8753593)
- Merola et al. 2012 (PLoS ONE e47653)
- Bekoff 1995 (Animal Studies Repository abstract page)
- Byosiere et al. 2016 (PLoS ONE e0168570); Byosiere et al. 2016 adult dogs (OpenAlex/S2 records only)
- Horowitz 2009 (Europe PMC, PMID 18679727)
- Rooney et al. 2001 (OpenAlex record; numbers only via Simonet 2005)
- Simonet, Versteeg, Storie 2005 (PDF, laughing-dog.petalk.org)
- Volsche et al. 2023 (eScholarship PDF, IJCP 35)
- Quaranta et al. 2007 (Europe PMC/OpenAlex records; content via Artelle 2010)
- Artelle, Dumoulin, Reimchen 2010 (UVic PDF)
- Siniscalchi et al. 2013 (Europe PMC, PMID 24184108)
- Waller et al. 2013 (PLoS ONE e82686)
- Kaminski et al. 2017 (Europe PMC, PMID 29051517)
- Wan, Bolger, Champagne 2012 (PLoS ONE e51775)
- Hsu & Serpell 2003 (Europe PMC, PMID 14621216); C-BARQ site
- Topal et al. 1998 (Europe PMC, PMID 9770312)
- Rehn et al. 2014 (Europe PMC, PMID 24471179); Rehn & Keeling 2011 (OpenAlex record only)
- Arkin, Fujita, Takagi, Hasegawa 2003 (GaTech PDF)
- Fujita 2004 (OpenAlex abstract)
- Sony aibo ERS-1000 Help Guide (four pages)
- Mitchinson & Prescott 2016 (White Rose preprint PDF)
- Lakatos et al. 2025 (Europe PMC, PMID 40461921; Crossref)
- Yang, Biernacka, Bruno 2025 (OpenAlex abstract)
- Gupta et al. 2024 (arXiv 2403.17270)
- Chakravarty et al. 2023 e-Inu (arXiv 2301.00964)
- Ribeiro & Paiva 2019 (arXiv 1904.02898 PDF)
- Takayama, Dooley, Ju 2011 (prepress PDF)
- Schulz, Torresen, Herstad 2019 (Semantic Scholar abstract)
- Hielscher, Bulling, Arras 2025 (arXiv 2504.06735 HTML)
- Grandia et al. 2025 Disney (arXiv 2501.05204 HTML)
- Watanabe, Li, Hutter 2025 DFM (arXiv 2502.10980 HTML)
- Heyrman et al. 2025 MDME (arXiv 2512.07673 HTML)
- Palucki et al. 2026 Kine2Go (arXiv 2606.14433 HTML)
- Marmpena et al. 2022 (arXiv 2205.00763)
- Cuan et al. 2023 Music Mode (arXiv 2306.02632)
- Bartneck et al. 2009 (bartneck.de); Bartneck 2023 chapter PDF; Weiss & Bartneck 2015 (OpenAlex)
- Carpinella et al. 2017 RoSAS (Semantic Scholar record; GMU scale database); Pan, Croft, Niemeyer 2017 (UBC PDF)
- Hauser et al. 2023 (OpenAlex abstract)
- Rogel, Yadollahi, Laban 2026 Reachy Mini (arXiv 2605.12786 HTML)
- Unitree: sport_client.hpp, sport_api.py, go2_sport_client.py, unitree_ros2 go2_sport_client.cpp (GitHub); DeepWiki (AI-generated, low trust)
