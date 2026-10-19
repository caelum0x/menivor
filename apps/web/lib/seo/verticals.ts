/**
 * "Video ads for <business type>" dataset for `/video-ads/{slug}`.
 *
 * Each vertical is written by hand for that business: what to paste, three
 * example opening hooks (written by us as illustrations, never presented as
 * customer results), what to show on screen and the ad-policy or craft points
 * that matter for that business. No statistics, testimonials or customer
 * names. A page whose entry is missing any of that is served `noindex`
 * (see {@link isIndexableVertical}), so thin pages never reach the index.
 */

export interface VerticalHook {
  /** The opening line, as it would be spoken in the first seconds. */
  readonly line: string;
  /** Why this opening works (the angle). */
  readonly angle: string;
}

export interface VerticalFaq {
  readonly question: string;
  readonly answer: string;
}

export interface Vertical {
  /** URL segment: `/video-ads/{slug}`. */
  readonly slug: string;
  /** Singular business name, lowercase: "dental clinic". */
  readonly business: string;
  /** Plural used in the H1: "dental clinics". */
  readonly plural: string;
  /** Primary keyword phrase for metadata. */
  readonly keyword: string;
  /** One-sentence lede under the H1. */
  readonly lede: string;
  /** What link to paste for this business and what Menivor takes from it. */
  readonly paste: string;
  /** Placeholder shown in the example input. */
  readonly exampleLink: string;
  /** Three example opening hooks, written by us. */
  readonly hooks: readonly VerticalHook[];
  /** What the reel should show on screen for this business. */
  readonly show: readonly string[];
  /** Ad-policy and craft points specific to this business. */
  readonly tips: readonly string[];
  readonly faqs: readonly VerticalFaq[];
}

export const VERTICALS: readonly Vertical[] = [
  {
    slug: "dental-clinic",
    business: "dental clinic",
    plural: "dental clinics",
    keyword: "video ads for dental clinics",
    lede: "Short vertical ads that make booking a check-up feel easy, from the link to your clinic's website.",
    paste: "Paste your clinic's website or its booking page. Menivor reads your treatments, opening hours, location and photos from the page, and writes three scripts around them.",
    exampleLink: "https://yourclinic.com",
    hooks: [
      { line: "Booking a dentist should take less time than brushing your teeth.", angle: "Removes the friction of booking, the real reason people put it off." },
      { line: "Here is exactly what happens at your first visit with us.", angle: "Walks through the visit step by step, which lowers the fear of the unknown." },
      { line: "Open on Saturdays, five minutes from [your neighborhood].", angle: "Leads with the practical detail people filter on: time and distance." },
    ],
    show: [
      "The front desk, a treatment room and a friendly face, from your own photos",
      "The booking screen, so viewers see how short it is",
      "Your address and hours as the closing card",
    ],
    tips: [
      "Health ads must not assert or imply things about the viewer's health (\"Are your teeth ruining your smile?\"). Speak about your clinic, not the viewer's condition; all three example hooks follow that rule.",
      "Skip before-and-after claims and price promises unless you can back them up; platforms review medical ads more strictly.",
    ],
    faqs: [
      { question: "Can I show real patients?", answer: "Only with their written consent. Menivor can narrate the script over your clinic footage instead, so no patient has to appear." },
      { question: "Which link works best?", answer: "Your booking page or a treatment page with clear text and photos. The more the page says, the more specific the scripts are." },
    ],
  },
  {
    slug: "real-estate-agent",
    business: "real estate agent",
    plural: "real estate agents",
    keyword: "video ads for real estate agents",
    lede: "Turn a listing link into three vertical listing tours with a voiceover and captions, ready for Reels and TikTok.",
    paste: "Paste a listing page, from your own site or a portal. Menivor uses the photos, rooms, price and neighborhood from the page and writes the tour script.",
    exampleLink: "https://yourbrokerage.com/listings/12-oak-street",
    hooks: [
      { line: "Three bedrooms, a garden, and a kitchen you will actually cook in.", angle: "Leads with the features buyers search for, in plain words." },
      { line: "Walk through [street name] with me in thirty seconds.", angle: "Promises a fast tour, which keeps viewers to the end." },
      { line: "The one room that sells this house is not the one you think.", angle: "Curiosity opening that pays off with the listing's best photo." },
    ],
    show: [
      "The listing photos in the order a buyer would walk through the home",
      "Room names and the key numbers (bedrooms, size) as captions",
      "Your name and how to book a viewing as the last card",
    ],
    tips: [
      "Housing ads on Meta must run under the Housing special ad category, which limits targeting by age, gender and ZIP code. Plan audiences with that in mind.",
      "Describe the property, never the kind of person who should live there; fair housing rules apply to ad copy too.",
    ],
    faqs: [
      { question: "Can I make one reel per listing?", answer: "Yes. Each link is its own run, and every run gives you three variants with different opening hooks." },
      { question: "Will the tour use my photos?", answer: "Yes, the images from the listing page are the footage; the voiceover and captions sit on top." },
    ],
  },
  {
    slug: "saas",
    business: "SaaS company",
    plural: "SaaS companies",
    keyword: "video ads for SaaS",
    lede: "From your landing page to three product ads that show the software working, with a hook, a voiceover and captions.",
    paste: "Paste your landing page. Menivor reads your headline, features and pricing, can record a scroll-through of the page, and writes three scripts built on the problem you solve.",
    exampleLink: "https://yourproduct.com",
    hooks: [
      { line: "You are still doing this in a spreadsheet?", angle: "Names the old way the buyer is stuck with, then shows the product replacing it." },
      { line: "Here is the whole setup, start to finish, in one take.", angle: "Proves it is easy by showing, not claiming." },
      { line: "We built this because [the painful task] took our team every Friday.", angle: "Founder story opening; honest and specific beats polished." },
    ],
    show: [
      "The product itself: a screen recording of the one workflow that matters",
      "The before (the old tool or manual step) for two seconds, then the after",
      "The price or the free trial offer on the last card",
    ],
    tips: [
      "One feature per ad. Three variants with three different hooks tell you which problem your buyers care about.",
      "Keep interface text large enough to read on a phone; zoom into the part of the screen that matters.",
    ],
    faqs: [
      { question: "Can it record my app?", answer: "Menivor can record a scroll-through of a public web page. For a logged-in product, upload a short screen recording and it becomes the footage." },
      { question: "Is this good for B2B?", answer: "Yes, as long as the ad shows a concrete task. Short product demos work on LinkedIn as well as on Reels and Shorts." },
    ],
  },
  {
    slug: "coffee-shop",
    business: "coffee shop",
    plural: "coffee shops",
    keyword: "video ads for coffee shops",
    lede: "Three short ads for your café from its website or Instagram profile: the drinks, the room and the reason to come in today.",
    paste: "Paste your café's website, Google Maps listing or Instagram profile. Menivor picks up your menu, photos, hours and address.",
    exampleLink: "https://instagram.com/yourcafe",
    hooks: [
      { line: "Your coffee is ready before your train is.", angle: "Ties the café to a daily habit and a practical need." },
      { line: "This is what we pour at 7 a.m. on a Monday.", angle: "Behind-the-counter moment that feels real, not staged." },
      { line: "The drink regulars order and never post about.", angle: "Curiosity about an off-menu favorite, which gets people in to try it." },
    ],
    show: [
      "Close-ups of drinks being made, from your own photos or clips",
      "The room: seats, light, the counter",
      "The address and a simple offer on the last card",
    ],
    tips: [
      "Local ads live or die on location. Put the neighborhood in the first sentence and the address on the last card.",
      "Post the winning variant as a regular Reel too; local followers share café content more than ads.",
    ],
    faqs: [
      { question: "I only have an Instagram account. Is that enough?", answer: "Yes. Paste the profile link; Menivor uses the public photos and the bio." },
      { question: "Can the reel be in Turkish?", answer: "Yes. Scripts and voiceovers can be English or Turkish, and the caption fonts include Turkish characters." },
    ],
  },
  {
    slug: "gym",
    business: "gym",
    plural: "gyms",
    keyword: "video ads for gyms",
    lede: "Short, energetic ads for your gym or fitness studio: the space, the classes and the first-visit offer.",
    paste: "Paste your gym's website or class schedule page. Menivor uses your classes, prices, photos and location.",
    exampleLink: "https://yourgym.com/classes",
    hooks: [
      { line: "Your first class is on us. Here is what it looks like.", angle: "Makes the free trial concrete, which is what gets people through the door." },
      { line: "No mirrors-and-ego energy. Just people getting stronger.", angle: "Speaks to the fear of feeling judged at a new gym." },
      { line: "Open at 5:30 a.m. for people who train before work.", angle: "Leads with the schedule detail that decides the choice." },
    ],
    show: [
      "The floor, the equipment and a class in progress",
      "The schedule or the trial offer as captions",
      "The address and the sign-up step on the last card",
    ],
    tips: [
      "Fitness ads must not imply the viewer's body or weight (\"Tired of your belly?\"). Talk about the gym, the classes and the community.",
      "Avoid promising specific results in a set time; platforms reject those claims.",
    ],
    faqs: [
      { question: "Can I make one ad per class type?", answer: "Yes. Paste a page for each class, or type a topic like \"our 6 a.m. spin class\", and each run gives three variants." },
      { question: "Do I need to film anything?", answer: "No. Menivor works from the photos on your page and a natural AI voice; your own clips make it stronger." },
    ],
  },
  {
    slug: "ecommerce-store",
    business: "online store",
    plural: "online stores",
    keyword: "video ads for ecommerce",
    lede: "Paste a product page and get three product ads with different hooks, built from your own photos, features and reviews.",
    paste: "Paste a product page from your store (Shopify and most storefronts work). Menivor reads the title, price, features, photos and the reviews shown on the page.",
    exampleLink: "https://yourstore.com/products/linen-shirt",
    hooks: [
      { line: "This is the shirt I wear when I do not want to think about what to wear.", angle: "First-person, everyday use; reads like a customer, not an ad." },
      { line: "Three things you only notice after a week with it.", angle: "List hook that keeps people watching for all three." },
      { line: "Why it costs what it costs.", angle: "Tackles the price objection head on with materials and making." },
    ],
    show: [
      "The product photos, closest detail shots first",
      "One feature per caption, in the words on your product page",
      "Price and the product name on the last card",
    ],
    tips: [
      "Test hooks, not edits. The three variants differ in their opening line, which is where most viewers decide to stay or scroll.",
      "Only quote reviews that are real and on your page; Menivor uses the reviews it finds there and never invents any.",
    ],
    faqs: [
      { question: "Does it work with marketplace listings?", answer: "Menivor reads structured product data from most storefronts and marketplace pages. If a page blocks automated reading, upload the photos instead." },
      { question: "How many products can I do?", answer: "One credit is one rendered reel, and the pricing page lists the pack sizes, so a catalog of best sellers is realistic." },
    ],
  },
  {
    slug: "restaurant",
    business: "restaurant",
    plural: "restaurants",
    keyword: "video ads for restaurants",
    lede: "Three short ads for your restaurant from its website, menu or Google listing: the dishes, the room and the reason to book tonight.",
    paste: "Paste your restaurant's website, menu page or Google Maps listing. Menivor uses the dishes, photos, hours and booking link.",
    exampleLink: "https://yourrestaurant.com/menu",
    hooks: [
      { line: "The dish our kitchen argues about every week.", angle: "Story around one signature dish; specific beats a full menu." },
      { line: "Table for two on a Tuesday? Here is why it is worth it.", angle: "Targets slow nights, when an ad is worth the most." },
      { line: "From the pass to your table in forty seconds.", angle: "Kitchen footage feels real and makes people hungry." },
    ],
    show: [
      "Close-ups of two or three dishes, from your photos",
      "The room at the time you want to fill",
      "The booking step on the last card",
    ],
    tips: [
      "Run a separate reel for each slow day or menu, not one ad for everything.",
      "If you serve alcohol, keep it in the background; alcohol ads have age and country restrictions.",
    ],
    faqs: [
      { question: "Can it read my PDF menu?", answer: "Menivor reads web pages. If your menu is a PDF, paste the restaurant's home page or type the dishes as a topic." },
      { question: "Can I add my own kitchen clips?", answer: "Yes. Open any variant in the Chop editor to swap in your own clips before you download." },
    ],
  },
  {
    slug: "mobile-app",
    business: "app developer",
    plural: "app developers",
    keyword: "video ads for mobile apps",
    lede: "Paste your App Store or Google Play link and get three app-install ads that show the app in use, with a hook, a voiceover and captions.",
    paste: "Paste the App Store or Google Play listing. Menivor uses the screenshots, the description and the reviews on the listing to write and build the ads.",
    exampleLink: "https://apps.apple.com/app/id0000000000",
    hooks: [
      { line: "I deleted four apps after I found this one.", angle: "Replacement story; positions the app against the category, not a named rival." },
      { line: "Watch me do [the core task] in under ten seconds.", angle: "A timed demo is proof, not a claim." },
      { line: "The setting nobody tells you about.", angle: "Curiosity that ends on the feature that makes the app sticky." },
    ],
    show: [
      "The app's own screens, in the order a new user sees them",
      "One tap or result per caption",
      "The store badge and the app name on the last card",
    ],
    tips: [
      "Show the app in the first two seconds; install ads that open with a talking head alone lose people early.",
      "Make one variant per core use case and keep the one with the best hold rate.",
    ],
    faqs: [
      { question: "Do I need to record the app?", answer: "No. The store screenshots are enough for a first ad. A short screen recording makes it stronger and can be uploaded." },
      { question: "What size is the export?", answer: "1080×1920 MP4, the native size for TikTok, Reels and Shorts." },
    ],
  },
  {
    slug: "hair-salon",
    business: "hair salon",
    plural: "hair salons",
    keyword: "video ads for hair salons",
    lede: "Short ads that fill your chairs: your styles, your stylists and the booking link, from your website or Instagram.",
    paste: "Paste your salon's Instagram profile, website or booking page. Menivor uses your photos, services, prices and location.",
    exampleLink: "https://instagram.com/yoursalon",
    hooks: [
      { line: "Bring a photo. We will tell you honestly if it works for your hair.", angle: "Trust opening; honesty is rare in beauty ads and stands out." },
      { line: "What a two-hour color appointment actually looks like.", angle: "Process content that sets expectations and shows skill." },
      { line: "Last-minute slots this week, [your neighborhood].", angle: "Fills gaps in the calendar with a clear, local call." },
    ],
    show: [
      "Finished styles from your own photos",
      "A stylist at work, with the service name as a caption",
      "Prices from and the booking step on the last card",
    ],
    tips: [
      "Use only photos of your own work, with clients' permission.",
      "Make one reel per service (cuts, color, treatments); the audiences differ.",
    ],
    faqs: [
      { question: "Can it use my Instagram photos?", answer: "Yes, the public photos on the profile you paste." },
      { question: "Can I make a reel for a single service?", answer: "Yes. Paste that service's page, or type it as a topic." },
    ],
  },
  {
    slug: "law-firm",
    business: "law firm",
    plural: "law firms",
    keyword: "video ads for law firms",
    lede: "Clear, calm explainer ads for your practice: what you handle, how the first consultation works and how to reach you.",
    paste: "Paste your firm's website or a practice-area page. Menivor uses your practice areas, location and contact details, and writes plain-language scripts.",
    exampleLink: "https://yourfirm.com/practice-areas/employment",
    hooks: [
      { line: "What to bring to your first meeting with an employment lawyer.", angle: "Useful first; the viewer learns something even if they never call." },
      { line: "Three questions we ask in every free consultation.", angle: "Shows how you work, which builds trust before contact." },
      { line: "Plain answers about [practice area], in under a minute.", angle: "Promises clarity, the thing people want most from lawyers." },
    ],
    show: [
      "A calm voiceover over your own photo, with the practice area as a title",
      "Each answer as a short caption",
      "The firm name, location and contact step on the last card",
    ],
    tips: [
      "Attorney advertising rules vary by jurisdiction: avoid promising outcomes and check whether ads need a disclaimer where you practice.",
      "Educational openings perform better and carry less risk than promises.",
    ],
    faqs: [
      { question: "Does anyone appear on camera?", answer: "No. The reel narrates the script over your footage with a calm voice and captions, which suits a firm's tone." },
      { question: "Can I review the script first?", answer: "Yes. You see and can edit every script in the editor before downloading." },
    ],
  },
  {
    slug: "plumber",
    business: "plumber",
    plural: "plumbers and home services",
    keyword: "video ads for plumbers",
    lede: "Short ads for plumbing and home-service businesses: what you fix, how fast you come and how to call.",
    paste: "Paste your website or Google Business profile. Menivor uses your services, service area, hours and reviews.",
    exampleLink: "https://yourplumbing.com",
    hooks: [
      { line: "Water where it should not be? Here is what to do in the next five minutes.", angle: "Useful emergency advice first, then the call to action." },
      { line: "We show the price before we pick up a wrench.", angle: "Addresses the fear of surprise bills." },
      { line: "Serving [your area] seven days a week.", angle: "Local and available: the two things people search for." },
    ],
    show: [
      "Your van, your team, your work, from your photos",
      "The service area and hours as captions",
      "The phone number or booking step on the last card",
    ],
    tips: [
      "Only promise response times you meet every time; ads that overpromise lead to bad reviews.",
      "Run separate reels for emergency work and planned jobs; the tone is different.",
    ],
    faqs: [
      { question: "Does it work for electricians, roofers and cleaners?", answer: "Yes. The flow is the same: paste your site or profile and pick the variant that fits." },
      { question: "Can the reel show my phone number?", answer: "Yes. Put it on the last card in the editor." },
    ],
  },
  {
    slug: "yoga-studio",
    business: "yoga studio",
    plural: "yoga studios",
    keyword: "video ads for yoga studios",
    lede: "Calm, welcoming ads for your studio: the room, the classes and an easy first step for beginners.",
    paste: "Paste your studio's website or schedule page. Menivor uses your classes, teachers, prices and photos.",
    exampleLink: "https://yourstudio.com/schedule",
    hooks: [
      { line: "Never done yoga? This is the class we built for you.", angle: "Beginners are the biggest audience and the most hesitant." },
      { line: "An hour where nobody needs anything from you.", angle: "Sells the feeling, not the poses." },
      { line: "Meet [teacher name] before your first class.", angle: "A familiar face lowers the barrier to walking in." },
    ],
    show: [
      "The studio space and a class from your photos",
      "Class names and times as captions",
      "The intro offer on the last card",
    ],
    tips: [
      "Avoid health or medical claims (\"cures back pain\"); describe the class instead.",
      "Keep the voiceover calm; the energetic style suits gyms, not studios.",
    ],
    faqs: [
      { question: "Can I choose a calmer voice?", answer: "Yes. Pick the voice before you start; the default works if you skip it." },
      { question: "Can I promote a workshop instead of classes?", answer: "Yes. Paste the workshop page or type it as a topic." },
    ],
  },
  {
    slug: "bakery",
    business: "bakery",
    plural: "bakeries",
    keyword: "video ads for bakeries",
    lede: "Short ads for your bakery: what comes out of the oven, when, and how to order ahead.",
    paste: "Paste your bakery's website, order page or Instagram profile. Menivor uses your products, photos, hours and address.",
    exampleLink: "https://yourbakery.com",
    hooks: [
      { line: "Out of the oven at 7. Gone by 10.", angle: "Real scarcity from your daily routine, not invented urgency." },
      { line: "How we make our sourdough, start to finish.", angle: "Process content that shows care and craft." },
      { line: "Order the birthday cake by Thursday, pick it up Saturday.", angle: "Clear, practical offer with a deadline that is real." },
    ],
    show: [
      "Bread and pastries from your photos, close up",
      "Hours or the order deadline as captions",
      "The address or order link on the last card",
    ],
    tips: [
      "Only use time claims that are true every day; regulars will notice.",
      "Custom orders (cakes, catering) deserve their own reel.",
    ],
    faqs: [
      { question: "Can I promote pre-orders?", answer: "Yes. Paste your order page and the scripts lead with ordering ahead." },
      { question: "Is three variants too many for a small bakery?", answer: "You keep the one you like and download it; the other two cost nothing extra." },
    ],
  },
  {
    slug: "online-course",
    business: "course creator",
    plural: "online course creators",
    keyword: "video ads for online courses",
    lede: "Turn your course sales page into three ads that show what students learn and who the course is for.",
    paste: "Paste your course's sales page. Menivor uses the curriculum, the outcomes you list, the price and your photos.",
    exampleLink: "https://yourschool.com/course",
    hooks: [
      { line: "Lesson one of my course, free, in sixty seconds.", angle: "Gives real value up front, which is the best proof." },
      { line: "This course is not for you if you want shortcuts.", angle: "Qualifies the audience; the right people lean in." },
      { line: "What you will be able to do by the end of week one.", angle: "A concrete, near-term outcome instead of a vague promise." },
    ],
    show: [
      "A slide or screen from the course itself",
      "The curriculum as short captions",
      "The price or enrollment date on the last card",
    ],
    tips: [
      "Avoid income claims (\"make $10k a month\"); platforms restrict them and viewers distrust them.",
      "Teaching in the ad works better than talking about teaching.",
    ],
    faqs: [
      { question: "Can I use my own face?", answer: "Yes. Upload a clip and use it in the editor as the footage under the voiceover." },
      { question: "Can I run ads before launch?", answer: "Yes. Paste your pre-launch sign-up page; the scripts point to signing up." },
    ],
  },
  {
    slug: "car-dealership",
    business: "car dealership",
    plural: "car dealerships",
    keyword: "video ads for car dealerships",
    lede: "Paste a vehicle listing and get three walkaround-style ads with the car's key specs as captions.",
    paste: "Paste a vehicle listing from your site. Menivor uses the photos, make, model, mileage, price and features on the page.",
    exampleLink: "https://yourdealership.com/inventory/2021-hatchback",
    hooks: [
      { line: "Low miles, one owner, and the trunk space families ask about.", angle: "Leads with the facts buyers filter on." },
      { line: "A thirty-second walkaround of this [model].", angle: "Short tour format that is easy to watch to the end." },
      { line: "Test-drive it this weekend. Here is what to look for.", angle: "Useful checklist, then the booking step." },
    ],
    show: [
      "The listing photos, exterior first, then interior",
      "Key specs as captions",
      "Price and the test-drive step on the last card",
    ],
    tips: [
      "If the ad mentions financing, it may fall under credit ad rules (on Meta, the Financial products and services special ad category). Keep financing terms accurate and complete.",
      "One car per reel; inventory ads work best when specific.",
    ],
    faqs: [
      { question: "Can I do my whole inventory?", answer: "Each listing is one run with three variants. Packs make a batch of listings affordable." },
      { question: "What if the listing has few photos?", answer: "The ad uses what the page has. More photos give a better walkaround." },
    ],
  },
  {
    slug: "boutique-hotel",
    business: "boutique hotel",
    plural: "hotels and guesthouses",
    keyword: "video ads for hotels",
    lede: "Short ads that make people picture their stay: the rooms, the view and the reason to book direct.",
    paste: "Paste your hotel's website or a room page. Menivor uses your rooms, photos, location and amenities.",
    exampleLink: "https://yourhotel.com/rooms",
    hooks: [
      { line: "Wake up to this, [your town].", angle: "Opens on the view or the room, which is what people book." },
      { line: "Five minutes from the old town, far from the noise.", angle: "Location plus quiet: two common reasons to choose." },
      { line: "What booking direct gets you that the big sites do not.", angle: "Gives a reason to book on your own site." },
    ],
    show: [
      "Rooms and the view from your photos",
      "Amenities as short captions",
      "The booking step on the last card",
    ],
    tips: [
      "Only mention direct-booking perks you actually offer.",
      "Seasonal reels (summer, winter weekends) keep ads relevant.",
    ],
    faqs: [
      { question: "Can I make reels in Turkish for local guests?", answer: "Yes. Scripts and voiceovers can be English or Turkish." },
      { question: "Does it work for guesthouses and rentals?", answer: "Yes. Paste the listing or website; the flow is the same." },
    ],
  },
  {
    slug: "photographer",
    business: "photographer",
    plural: "photographers",
    keyword: "video ads for photographers",
    lede: "Turn your portfolio into three short ads that show your style and how a shoot works.",
    paste: "Paste your portfolio site or Instagram profile. Menivor uses your photos, services and packages.",
    exampleLink: "https://yourportfolio.com",
    hooks: [
      { line: "What a shoot with me actually feels like.", angle: "Most clients are nervous about being photographed; this answers it." },
      { line: "Three photos, and the story behind each one.", angle: "Story format that shows your eye, not just your gear." },
      { line: "Booking [season] sessions now, [your city].", angle: "Clear, local and timed." },
    ],
    show: [
      "Your best photos, one per beat",
      "Package names as captions",
      "The booking step on the last card",
    ],
    tips: [
      "Use only images you have the right to use in ads, with model releases where people appear.",
      "Make one reel per shoot type (weddings, portraits, products).",
    ],
    faqs: [
      { question: "Will it crop my photos?", answer: "The reel is vertical (9:16), so wide photos are framed with motion; you can adjust framing in the editor." },
      { question: "Does anyone appear on screen?", answer: "No. Every reel narrates the script with a voice over moving footage; nobody appears on camera." },
    ],
  },
  {
    slug: "auto-repair-shop",
    business: "auto repair shop",
    plural: "auto repair shops",
    keyword: "video ads for auto repair shops",
    lede: "Short, trustworthy ads for your garage: what you fix, how you price and how to book.",
    paste: "Paste your shop's website or Google Business profile. Menivor uses your services, hours, location and reviews.",
    exampleLink: "https://yourgarage.com",
    hooks: [
      { line: "That noise your car makes? Here is what it usually means.", angle: "Useful first; people remember the shop that explained it." },
      { line: "We send you a photo of the problem before we fix it.", angle: "Transparency answers the biggest fear: being overcharged." },
      { line: "Same-week appointments in [your area].", angle: "Practical and local." },
    ],
    show: [
      "The workshop and your team from your photos",
      "Services as short captions",
      "The booking step on the last card",
    ],
    tips: [
      "Only describe processes you follow every time.",
      "Seasonal checks (winter tires, AC) make good timely reels.",
    ],
    faqs: [
      { question: "Can I use it for a tire shop or body shop?", answer: "Yes. Paste that business's page; the scripts follow what the page offers." },
      { question: "Do I need video footage?", answer: "No. Photos from your page are enough for a first ad." },
    ],
  },
  {
    slug: "cleaning-service",
    business: "cleaning service",
    plural: "cleaning services",
    keyword: "video ads for cleaning services",
    lede: "Short ads for home and office cleaning: what is included, how booking works and the area you cover.",
    paste: "Paste your cleaning company's website or booking page. Menivor uses your services, prices, area and photos.",
    exampleLink: "https://yourcleaning.com",
    hooks: [
      { line: "Everything we clean in a standard visit, in thirty seconds.", angle: "Spells out what is included, the top question people have." },
      { line: "Book in two minutes. Come home to this.", angle: "Easy booking plus the result." },
      { line: "Same cleaner every time, [your city].", angle: "Consistency and trust are what regular customers want." },
    ],
    show: [
      "Finished rooms from your photos",
      "The checklist as captions",
      "Price from and the booking step on the last card",
    ],
    tips: [
      "Show only your own work and staff, with their consent.",
      "Separate reels for homes, offices and move-out cleans.",
    ],
    faqs: [
      { question: "Can it list my prices?", answer: "If they are on the page you paste, yes. Otherwise add them in the editor." },
      { question: "Can I target one neighborhood?", answer: "Targeting happens in your ad account; the reel can name the area in its first line." },
    ],
  },
  {
    slug: "language-school",
    business: "language school",
    plural: "language schools and tutors",
    keyword: "video ads for language schools",
    lede: "Ads that teach a little and sell a lot: a real phrase, how your classes work and when the next course starts.",
    paste: "Paste your school's website or course page. Menivor uses your languages, levels, schedule and prices.",
    exampleLink: "https://yourschool.com/english",
    hooks: [
      { line: "Say this at your next job interview in English.", angle: "Teaches one useful phrase; the ad itself is proof of the teaching." },
      { line: "From zero to your first conversation: what the first month looks like.", angle: "Concrete path instead of vague fluency promises." },
      { line: "New evening group starts [date], [your city].", angle: "A real start date gives a real reason to act now." },
    ],
    show: [
      "A classroom or online lesson from your photos",
      "The phrase or lesson plan as captions",
      "The start date and sign-up step on the last card",
    ],
    tips: [
      "Avoid promising fluency in a fixed time; it is the claim viewers trust least.",
      "Bilingual captions (for example English and Turkish) help the learner follow.",
    ],
    faqs: [
      { question: "Can the voiceover be in Turkish while teaching English?", answer: "Yes. Scripts and voiceovers can be English or Turkish; write the phrase you teach into the script in the editor." },
      { question: "Does it work for private tutors?", answer: "Yes. Paste your profile or website; the flow is the same." },
    ],
  },
];

/** A page is indexable only when its entry has all the unique parts. */
export function isIndexableVertical(vertical: Vertical): boolean {
  return (
    vertical.hooks.length >= 3 &&
    vertical.show.length >= 2 &&
    vertical.tips.length >= 1 &&
    vertical.faqs.length >= 1 &&
    vertical.paste.length > 40 &&
    vertical.lede.length > 40
  );
}

export function getVertical(slug: string): Vertical | undefined {
  return VERTICALS.find((vertical) => vertical.slug === slug);
}

export const VERTICAL_SLUGS: readonly string[] = VERTICALS.map((vertical) => vertical.slug);

/** Slugs that belong in the sitemap (indexable pages only). */
export const INDEXABLE_VERTICAL_SLUGS: readonly string[] = VERTICALS.filter(isIndexableVertical).map(
  (vertical) => vertical.slug,
);

/** Up to `count` other verticals, starting after this one, for cross-links. */
export function relatedVerticals(slug: string, count = 6): readonly Vertical[] {
  const index = VERTICALS.findIndex((vertical) => vertical.slug === slug);
  const rotated = [...VERTICALS.slice(index + 1), ...VERTICALS.slice(0, Math.max(index, 0))];
  return rotated.filter((vertical) => vertical.slug !== slug).slice(0, count);
}
