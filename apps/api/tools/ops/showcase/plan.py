"""Landing showcase reel plan: 27 reels, one niche each, nothing reused.

footage: Pexels video ids (Pexels License), cut into a montage for the product panel.
loop:    companion loop (bundled original loop name, or px:<id> Pexels clip,
         or "@footage" for the reel's own montage).
style:   pipeline style id, or "" for the classic full-bleed voiceover reel.
label:   the preset name shown on the landing tile.
page:    the live page an own-product reel records (its numbers must appear there).
The first paragraph of each script is the on-screen hook (POV line, meme band,
story card or before/after split, depending on the style).

Showcase rules (checked by ``checks.py`` and tests/reelforge/test_showcase_plan.py):
every reel moves, has sound and runs 20-40 s; one niche per reel; no two reels
share a niche, a footage clip, a background loop or a narrator voice; at most two
reels advertise our own products, in different styles; scripts for example
businesses carry no digit figures (nothing to fact-check against), and every
number in an own-product script appears in that product's page text.
"""

#: Seconds the pipeline aims for; the typed script sets the real length.
TARGET_DURATION_S = 28
#: Renders are bulk work: the lowest render lane (domains/reels/policy.py).
RENDER_LANE = "bulk"

REELS = [
    # --- D2C products ---------------------------------------------------------
    dict(key="serum-morning", niche="Skincare brand", style="", label="Voiceover reel",
         footage=["8131891", "7607767", "7305465"], loop="", voice="en-US-AriaNeural",
         captions="clean_white",
         script="This serum is the only step I never skip.\n\n"
                "Three drops in the morning, pressed in with warm hands, and my skin looks rested all day. "
                "It feels light, it leaves no sticky finish, and it layers under sunscreen and makeup "
                "without pilling. At night I use it again before moisturiser. "
                "If your skin looks tired by lunchtime, this is the one to try. Tap the link to get yours."),
    dict(key="ring-pov", niche="Jewelry shop", style="pov_text", label="POV text",
         footage=["31992241", "6262797", "6805433"], loop="marble-run-2.mp4", voice="en-US-EmmaNeural",
         script="POV: you finally found a ring you never take off\n\n"
                "Solid silver, polished by hand, and engraved with whatever you want it to say. "
                "It does not turn your finger green, it survives the shower, and it still shines a year later. "
                "Every ring ships in a small gift box, ready to give or to keep. "
                "Pick your size and your words at the link."),
    dict(key="sneaker-meme", niche="Sneaker brand", style="meme_hook", label="Meme hook",
         footage=["29892299", "31732972", "4941597"], loop="block-runner-3.mp4", voice="en-US-BrianNeural",
         script="Nobody: Me buying the same sneakers in a third colour\n\n"
                "In my defence, they go with everything. They break in on day one, "
                "they stay comfortable after a full day on my feet, and they still look clean after the rain. "
                "The sole grips, the laces stay tied, and the colours do not fade. "
                "Pick your colour at the link before your size sells out."),
    # --- Food and recipes ------------------------------------------------------
    dict(key="pasta-weeknight", niche="Weeknight recipes", style="", label="Voiceover reel",
         footage=["6289336", "12691875", "6222558"], loop="", voice="en-US-ChristopherNeural",
         captions="karaoke_yellow",
         script="The weeknight pasta I make when I am too tired to cook.\n\n"
                "Salt the water like the sea and get it boiling while you slice the garlic. "
                "Pull the pasta a minute early, then finish it in the pan with butter, garlic "
                "and a big splash of pasta water until it turns glossy. "
                "Lemon zest and pepper on top, and dinner is done. Full recipe at the link."),
    dict(key="smoothie-split", niche="Smoothie recipes", style="satisfying_split", label="Satisfying split",
         footage=["7930764", "8802325", "7930810"], loop="px:7467273", voice="en-US-AvaNeural",
         script="Here is the smoothie bowl nobody tells you how to get thick\n\n"
                "Use frozen fruit only, never ice, and add just a splash of milk. "
                "Blend on low and stop to scrape the sides, even when it looks like it will never come together. "
                "It will. Spoon it into a cold bowl and top it fast, before it melts. "
                "Save this for tomorrow morning."),
    dict(key="burger-pov", niche="Burger grill", style="pov_text", label="POV text",
         footage=["34803863", "31176159", "34697259"], loop="sand-slice-2.mp4", voice="en-US-GuyNeural",
         script="POV: you walked past our grill at lunchtime\n\n"
                "Every burger is smashed to order on a hot flat top, so the edges go crisp. "
                "The cheese melts right on the grill, the bun gets toasted in butter, "
                "and the pickles are made in our kitchen. "
                "Grab a table inside or take it to the park. Come hungry. Directions at the link."),
    dict(key="latte-cafe", niche="Corner cafe", style="", label="Voiceover reel",
         footage=["34601858", "38694343", "29296613"], loop="", voice="en-GB-SoniaNeural",
         captions="bold_violet",
         script="Every cup at our corner cafe gets poured by hand.\n\n"
                "The beans are roasted just down the road, the milk is steamed to order, "
                "and the pastries come out of the oven every morning. "
                "There is a quiet table by the window, good music, and nobody rushing you out. "
                "Bring a book or bring a friend. Come say hello this weekend."),
    dict(key="cooking-narrator", niche="Cooking class", style="character_story", label="Cartoon narrator",
         footage=["4252801", "6281198", "6286101"], loop="@footage", voice="en-US-RogerNeural",
         script="I signed up for a pasta class and it changed my Sundays\n\n"
                "I had never rolled dough in my life. The teacher showed us how to feel when it was ready, "
                "and by the end of the night I made a full tray of fresh pasta. "
                "I have been making it every weekend since, and my family now expects it. "
                "Book a seat at the link."),
    # --- Fitness ---------------------------------------------------------------
    dict(key="gym-split", niche="Fitness coach", style="gameplay_split", label="Gameplay split",
         footage=["35585700", "35585591", "4686178"], loop="block-runner-2.mp4", voice="en-GB-RyanNeural",
         script="POV: your training plan finally fits your week\n\n"
                "Three short sessions, one clear goal, and a coach who checks your form on video. "
                "No two-hour gym days, no guessing which exercise comes next. "
                "Every week gets a little harder, and you can see the progress in your notes and in the mirror. "
                "Start your first week at the link."),
    dict(key="trail-story", niche="Running club", style="story_gameplay", label="Story time",
         footage=["31921071", "36578163", "35799015"], loop="@footage", voice="en-AU-WilliamMultilingualNeural",
         script="I joined a running club to meet people and ended up loving the trail\n\n"
                "The first run I walked half of it. Nobody cared. Someone always waited at the top of the hill, "
                "and we finished together with coffee at the end. "
                "Now Saturday mornings are the best part of my week. "
                "Come run with us, all paces welcome. Details at the link."),
    # --- Travel ----------------------------------------------------------------
    dict(key="island-drone", niche="Island travel guide", style="", label="Voiceover reel",
         footage=["28615730", "32022379", "38005764"], loop="", voice="en-AU-NatashaNeural",
         captions="karaoke_green",
         script="Save this for the trip you keep putting off.\n\n"
                "Turquoise water, quiet beaches, and trails that end at a view like this. "
                "Go early in the morning, before the boats arrive, and you will have the coves to yourself. "
                "Our island guide maps every beach, every trail and every small place to eat. "
                "Link in bio."),
    dict(key="tokyo-meme", niche="City night tours", style="meme_hook", label="Meme hook",
         footage=["35291926", "31397167", "32287884"], loop="marble-run.mp4", voice="en-US-AndrewNeural",
         script="Me pretending I will sleep early on my first night in Tokyo\n\n"
                "Neon streets, the famous crossing, and a bowl of ramen at midnight. "
                "Then a tiny bar with six seats, and suddenly the trains have stopped. "
                "Our night walk guide shows you where to go, what to order and how to get back. "
                "Save it before you fly, so your first night is the one you remember. "
                "Link in bio."),
    dict(key="hike-pov", niche="Hiking tours", style="pov_text", label="POV text",
         footage=["34700249", "28185282", "31640241"], loop="sand-slice-3.mp4", voice="en-US-MichelleNeural",
         script="POV: you said yes to the sunrise hike\n\n"
                "A cold start in the dark, a misty trail with a head torch, and then this. "
                "Hot tea at the top, a guide who knows every turn, and a slow walk back down for breakfast. "
                "Our small group hikes leave every weekend. "
                "Grab a spot at the link."),
    # --- Real estate -----------------------------------------------------------
    dict(key="house-tour", niche="Real estate agent", style="", label="Voiceover reel",
         footage=["37522009", "38413576", "37674129"], loop="", voice="en-US-EricNeural",
         captions="clean_white",
         script="Walk through this home with me.\n\n"
                "A stone staircase as you come in, light in every room, "
                "and a kitchen built for long dinners with friends. "
                "Upstairs, the bedrooms look out over the garden, and the quiet street keeps it calm at night. There is even a small office under the stairs. "
                "Private viewings are open this week. Book yours at the link."),
    dict(key="kitchen-before-after", niche="Interior designer", style="before_after", label="Before / after",
         footage=["38413548", "36842451", "38413575"], loop="", voice="en-US-JennyNeural",
         script="Before: a dark kitchen nobody wanted to cook in. After: the room everyone ends up in.\n\n"
                "We kept the layout and changed the light. "
                "Warm lamps over the counter, open shelves instead of heavy cupboards, "
                "and a finish in natural stone and wood that gets better with age. Same room, same plumbing, a completely different feeling. Book a design call at the link."),
    # --- SaaS ------------------------------------------------------------------
    dict(key="saas-inbox", niche="Help desk software", style="gameplay_split", label="Gameplay split",
         footage=["34124550", "34771072", "8480685"], loop="block-runner-5.mp4", voice="en-US-SteffanNeural",
         script="Tell me you answer every support email without telling me\n\n"
                "Our help desk sorts your inbox by topic, pulls the order details in beside each message, "
                "and drafts a reply in your own tone. You read it, change what you want, and hit send. "
                "The questions that repeat get answered the same way every time. "
                "Try it on your own inbox at the link."),
    # --- Local business --------------------------------------------------------
    dict(key="barber-meme", niche="Barber shop", style="meme_hook", label="Meme hook",
         footage=["7697102", "7697084", "7697071"], loop="block-runner-4.mp4", voice="en-IE-ConnorNeural",
         script="You met me at a very overgrown time in my life\n\n"
                "Walk in, sit down, and walk out looking like yourself again. "
                "Skin fades, beard trims and hot towel shaves, done by barbers who ask what you want "
                "and actually listen. Coffee while you wait, and walk-ins are welcome in the morning. "
                "Book at the link."),
    dict(key="bakery-morning", niche="Bakery", style="", label="Voiceover reel",
         footage=["5757797", "5757795", "5877787"], loop="", voice="en-GB-LibbyNeural",
         captions="karaoke_yellow",
         script="Our bread comes out of the oven before the sun is up.\n\n"
                "Slow dough that rests overnight, a hot stone oven, and a crust that crackles when you press it. "
                "The cinnamon rolls come out next, still warm when the doors open, and the coffee is already on. "
                "Come early, because the sourdough goes first."),
    dict(key="car-before-after", niche="Car detailing", style="before_after", label="Before / after",
         footage=["32010552", "32010530", "32010555"], loop="", voice="en-CA-LiamNeural",
         script="Before: road salt, dull paint, brake dust. After: a finish you can see yourself in.\n\n"
                "Every detail starts with a hand wash and a clay bar, then a full polish and a protective coat. "
                "Inside, the seats get steamed, the vents get brushed out, and the mats come out looking new. "
                "Book your detail at the link."),
    dict(key="dog-groom-split", niche="Pet grooming", style="satisfying_split", label="Satisfying split",
         footage=["6132712", "6132713", "6131720"], loop="px:12681572", voice="en-US-AnaNeural",
         script="Nobody tells you how calm a dog can be at the groomer\n\n"
                "A warm bath, a slow blow dry, and a gentle trim, with a lot of treats along the way. "
                "We take our time with nervous dogs and stop whenever they need a break. "
                "Your dog leaves fluffy, happy and smelling great. Book a visit at the link."),
    dict(key="florist-story", niche="Flower shop", style="story_gameplay", label="Story time",
         footage=["6912181", "4621363", "6911314"], loop="@footage", voice="en-GB-MaisieNeural",
         script="I opened a tiny flower shop and this is what a Friday looks like\n\n"
                "Fresh stems arrive at dawn, and I spend the morning cutting, sorting and tying bouquets by hand. "
                "By the afternoon the counter is covered in orders, each one wrapped with a ribbon and a note. "
                "Order for the weekend at the link."),
    dict(key="power-wash", niche="Exterior cleaning", style="", label="Voiceover reel",
         footage=["6160411", "8242982", "6160418"], loop="", voice="en-NZ-MitchellNeural",
         captions="anime_pop",
         script="Watch years of grime come off in one pass.\n\n"
                "Driveways, patios and garden walls, cleaned with hot water and pressure, "
                "without harsh chemicals running into your plants. "
                "We seal the stone afterwards so it stays clean for longer, and we tidy up before we leave. "
                "Send us a photo of the job and get a quote at the link."),
    dict(key="candle-split", niche="Handmade candles", style="satisfying_split", label="Satisfying split",
         footage=["6748362", "8271971", "7234571"], loop="px:9736574", voice="en-NZ-MollyNeural",
         script="Here is what nobody tells you about hand-poured candles\n\n"
                "The wax matters, the wick matters, and the waiting matters most. "
                "We pour soy wax around a cotton wick, then let every candle cure slowly "
                "so the scent fills the room instead of fading after a week. "
                "Each one is poured in our studio. Shop the scents at the link."),
    dict(key="paint-meme", niche="Art class", style="meme_hook", label="Meme hook",
         footage=["6214405", "7151471", "6957793"], loop="block-runner-6.mp4", voice="en-IE-EmilyNeural",
         script="Me after one beginner painting class thinking I am an artist now\n\n"
                "No experience needed. The paint, the brushes and the canvas are all included, "
                "and the teacher walks you through every step at your own pace. "
                "You leave with a painting you made yourself, and a new hobby. "
                "Book a Thursday night at the link."),
    dict(key="cleaning-before-after", niche="Home cleaning", style="before_after", label="Before / after",
         footage=["9462882", "9462894", "4684442"], loop="", voice="en-CA-ClaraNeural",
         script="Before: a weekend lost to chores. After: a spotless home and your Saturday back.\n\n"
                "Our cleaners are vetted, they follow your own checklist, "
                "and you get the same team every visit, so they learn how you like things. "
                "Kitchens, bathrooms, floors and windows, all done while you are out living your weekend. "
                "Book a clean at the link."),
    # --- Our own products (max two, different styles) ---------------------------
    dict(key="menivor-pov", niche="Menivor (our product)", style="pov_text", label="POV text",
         footage=[], page="https://menivor.com", loop="block-runner.mp4", voice="en-IN-PrabhatNeural",
         script="POV: you pasted one link and got three reels back\n\n"
                "Menivor reads your page, writes the hook, voices it and captions it. "
                "You pick a style, like a split screen or a meme hook, and the reel comes back ready to post. "
                "No editing timeline, no stock search, no recording your own voice. "
                "Pick a style and paste your link."),
    dict(key="scribase-split", niche="Scribase (our product)", style="satisfying_split", label="Satisfying split",
         footage=[], page="https://scribase.com", loop="sand-slice.mp4", voice="en-GB-ThomasNeural",
         script="Here is what nobody tells you about shipping your app backend\n\n"
                "The database is the easy part. Auth, storage and keeping it all in sync is where the weekends go. "
                "Scribase gives you the database, auth and storage in one project, "
                "so you can get back to building the app your users actually see. "
                "Start one from the link."),
]
