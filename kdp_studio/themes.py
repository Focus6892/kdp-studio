"""Built-in library of coloring-book niches for the offline "Gợi ý" engine.

Each theme carries the nouns used in titles, seven KDP keywords (<= 50 chars each) and 30 page subjects
written for the bold-and-easy style: one concrete object or scene, large simple shapes, no people or
human figures (the interior QA rejects them), no text, no brands. `find_theme` maps whatever the user
typed ("ocenan", "sea creatures", "Ocean Animals Coloring Book") onto one of them, fuzzily.
"""

from __future__ import annotations

import difflib
import re

STYLE_WORDS = {"bold", "and", "easy", "simple", "large", "print", "coloring", "colouring", "book", "books", "pages", "page", "for", "adults", "kids", "beginners",
               "seniors", "designs", "cute", "relaxing", "big", "with", "the"}

THEMES: dict[str, dict] = {
    "ocean": {
        "aliases": ["sea", "marine", "underwater", "ocean animals", "sea animals", "sea creatures", "sea life", "fish", "beach"],
        "noun": "Ocean Animals", "sub": "Sea Creatures",
        "keywords": ["ocean coloring book", "sea animals coloring pages", "easy coloring book for kids", "bold and easy coloring book", "under the sea coloring",
                     "large print coloring book", "relaxing coloring book for adults"],
        "subjects": [
            "a smiling whale spouting water", "a sea turtle swimming over coral", "an octopus holding three shells", "a seahorse curled around a strand of seaweed",
            "a round pufferfish with big eyes", "a starfish resting on a sandy seabed", "a dolphin leaping over a wave", "a crab waving one claw on the beach",
            "a jellyfish with long wavy tentacles", "a clownfish peeking out of an anemone", "a hermit crab in a spiral shell", "a manta ray gliding with wide wings",
            "a friendly shark with a toothy grin", "a lobster among rocks and bubbles", "three small fish swimming together", "a seal balancing a ball on its nose",
            "a narwhal with a spiral tusk", "an angelfish with striped fins", "a walrus lounging on an ice floe", "a sea otter floating on its back holding a shell",
            "a treasure chest with pearls and seaweed", "a lighthouse on a rock with gentle waves", "a sailboat on calm water with a big sun", "a coral reef with three round fish",
            "a blue whale tail rising above the waves", "a squid with curly arms", "a penguin standing on an iceberg", "a sand dollar and two seashells on the beach",
            "an anchor wrapped in rope and seaweed", "a moon jellyfish under a crescent moon",
        ],
    },
    "flowers": {
        "aliases": ["flower", "floral", "blossom", "blossoms", "blooms", "botanical", "garden flowers", "roses", "tulips"],
        "noun": "Flowers", "sub": "Flower Designs",
        "keywords": ["flower coloring book", "floral coloring pages", "easy coloring book for adults", "bold and easy coloring book", "large print coloring book",
                     "relaxing coloring book", "coloring book for seniors"],
        "subjects": [
            "a single large daisy filling the page", "a tulip in a tall vase", "a rose with wide curled petals", "a sunflower with a big round center and wide petals",
            "a bouquet of tulips tied with ribbon", "a potted cactus with one bloom", "three poppies on long stems", "a lily with curling petals",
            "a lotus floating on a pond with lily pads", "a wreath of roses and leaves", "a hibiscus with a long stamen", "a basket of mixed wildflowers",
            "a lavender bunch tied with string", "a watering can with daisies spilling out", "a peony with layered petals", "a pair of daffodils with leaves",
            "a hanging planter with trailing flowers", "a flower mandala with eight petals", "a cherry blossom branch", "a garden gate with climbing roses",
            "a magnolia bloom on a branch", "a morning glory vine on a trellis", "a heart made of small flowers", "a teacup planted with pansies",
            "a dandelion with floating seeds", "a bluebell cluster with a bee", "a window box of geraniums", "an orchid with three blooms",
            "a daisy chain border around a single bloom", "a tulip field under a round sun",
        ],
    },
    "farm": {
        "aliases": ["farm animals", "barnyard", "countryside", "barn", "cows", "pigs", "chickens"],
        "noun": "Farm Animals", "sub": "Farm Friends",
        "keywords": ["farm animals coloring book", "barnyard coloring pages", "easy coloring book for kids", "bold and easy coloring book", "toddler coloring book animals",
                     "large print coloring book", "cute animals coloring book"],
        "subjects": [
            "a cow standing in a meadow", "a pig rolling in a mud puddle", "a rooster crowing on a fence", "a sheep with fluffy wool",
            "a hen with three chicks", "a horse looking over a stable door", "a goat standing on a hay bale", "a duck swimming in a pond",
            "a donkey with long ears beside a cart", "a barn with a big door and a weather vane", "a tractor in a field", "a cat napping on a hay bale",
            "a dog sitting beside a wooden fence", "a turkey with fanned tail feathers", "a rabbit nibbling a carrot in a garden", "a goose with its wings spread",
            "a calf drinking from a bucket", "a lamb jumping in clover", "a piglet with a curly tail", "a basket of eggs beside a hen",
            "a windmill on a hill", "a milk can and a pail of apples", "a pony with a flowing mane", "a sunflower patch by a fence",
            "a wheelbarrow full of pumpkins", "a cow bell hanging on a post with daisies", "a mother duck with ducklings in a row", "a bull with curved horns in a field",
            "a farm cat chasing a butterfly", "a pile of hay bales under a round sun",
        ],
    },
    "woodland": {
        "aliases": ["forest", "forest animals", "woodland animals", "woods", "foxes", "deer", "owls"],
        "noun": "Woodland Animals", "sub": "Forest Friends",
        "keywords": ["woodland animals coloring book", "forest animals coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "cute animals coloring book", "large print coloring book", "relaxing coloring book for adults"],
        "subjects": [
            "a fox curled up with its tail", "a bear cub holding a honey pot", "a deer with small antlers in a clearing", "a hedgehog with an apple on its back",
            "a raccoon peeking from a hollow log", "an owl perched on a branch", "a squirrel holding an acorn", "a rabbit beside a mushroom",
            "a moose standing in tall grass", "a beaver chewing a log by a river", "a badger walking under ferns", "a wolf howling at the moon",
            "a chipmunk with full cheeks", "a porcupine under an oak tree", "a skunk with a wide striped tail", "a sleepy bear in a cave entrance",
            "a woodpecker on a tree trunk", "a fawn lying in flowers", "three mushrooms growing together", "an otter on a river bank",
            "a pine tree with a bird nest", "a snail on a mossy stone", "a frog sitting on a lily pad", "a hollow log with a mouse inside",
            "a bird feeder with two chickadees", "an acorn and oak leaves", "a stag with wide antlers", "a hare in a snowy field",
            "a campfire ring with logs and a kettle", "a lantern hanging from a branch",
        ],
    },
    "dinosaurs": {
        "aliases": ["dinosaur", "dino", "dinos", "prehistoric", "t rex", "jurassic"],
        "noun": "Dinosaurs", "sub": "Dinosaur Designs",
        "keywords": ["dinosaur coloring book", "dinosaur coloring pages for kids", "easy coloring book for kids", "bold and easy coloring book",
                     "toddler coloring book dinosaurs", "large print coloring book", "cute dinosaur coloring book"],
        "subjects": [
            "a smiling T. rex with tiny arms", "a triceratops with three horns", "a stegosaurus with back plates", "a long-necked brontosaurus eating leaves",
            "a pterodactyl gliding over mountains", "a baby dinosaur hatching from an egg", "a dinosaur nest with three eggs", "a velociraptor running",
            "an ankylosaurus with a club tail", "a parasaurolophus with a head crest", "a spinosaurus with a sail on its back", "a volcano with smoke and palm trees",
            "a dinosaur footprint beside a fern", "a diplodocus under a round sun", "a brachiosaurus reaching a tall tree", "a dimetrodon with a big fin",
            "a plesiosaurus swimming", "an iguanodon with thumb spikes", "a pachycephalosaurus with a dome head", "two baby dinosaurs playing with a ball",
            "a dinosaur egg with spots", "a dinosaur in a jungle with big leaves", "a sleeping dinosaur under the moon", "a dinosaur with a party hat and balloons",
            "a dinosaur splashing in a pond", "a dinosaur with a birthday cake", "a prehistoric fern garden", "a dinosaur peeking from behind a rock",
            "a corythosaurus by a river", "a dinosaur mandala with eggs and leaves",
        ],
    },
    "vehicles": {
        "aliases": ["vehicle", "cars", "trucks", "transportation", "things that go", "construction", "trains"],
        "noun": "Vehicles", "sub": "Cars and Trucks",
        "keywords": ["vehicles coloring book", "cars and trucks coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "toddler coloring book trucks", "large print coloring book", "construction vehicles coloring"],
        "subjects": [
            "a dump truck full of rocks", "a fire engine with a ladder", "a school bus with round windows", "a race car with racing stripes",
            "a tractor pulling a trailer", "a steam train with a puff of smoke", "a hot air balloon over hills", "a sailboat on gentle waves",
            "a helicopter with spinning blades", "a monster truck with giant wheels", "a police car with a light bar", "a cement mixer truck",
            "an excavator digging a hole", "a bicycle with a basket of flowers", "a motorcycle with a sidecar", "a rocket ship blasting off",
            "a submarine with a periscope", "a tugboat in a harbor", "a camper van with a surfboard on top", "an ice cream truck",
            "a city bus at a stop", "a garbage truck lifting a bin", "a tow truck with a hook", "a jet plane in the clouds",
            "a scooter with a basket", "a tractor-trailer on a road", "a cable car on a wire", "a canoe with two paddles",
            "a forklift lifting a crate", "a bulldozer pushing dirt",
        ],
    },
    "space": {
        "aliases": ["outer space", "planets", "galaxy", "rockets", "solar system", "stars"],
        "noun": "Outer Space", "sub": "Space Adventures",
        "keywords": ["space coloring book", "planets coloring pages for kids", "easy coloring book for kids", "bold and easy coloring book",
                     "rocket coloring book", "large print coloring book", "solar system coloring book"],
        "subjects": [
            "a rocket ship with round windows", "a smiling planet with rings", "a crescent moon with stars", "a flying saucer with a beam of light",
            "a round blob alien with one big eye", "a comet with a long tail", "a satellite orbiting a planet", "a telescope pointing at the moon",
            "a space rover on a cratered surface", "a planet with a volcano", "a sun with wavy rays", "a space station with solar panels",
            "the earth with clouds", "a moon buggy with big wheels", "a star cluster mandala", "a shooting star over mountains",
            "a spiral galaxy", "a rocket landing on a planet", "a hot air balloon shaped like a planet", "a space helmet on a stand",
            "a planet with two moons", "a space shuttle", "a meteor shower over a desert", "a lunar lander",
            "a robot waving on a planet", "a ringed planet with striped bands", "a dog in a space suit", "a cat in a space suit floating",
            "a constellation shaped like a bear", "a moon with craters and a small rocket",
        ],
    },
    "sweets": {
        "aliases": ["desserts", "dessert", "candy", "cupcakes", "treats", "bakery", "cakes", "ice cream", "food"],
        "noun": "Sweet Treats", "sub": "Desserts and Candy",
        "keywords": ["sweet treats coloring book", "dessert coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "cupcake coloring book", "large print coloring book", "candy coloring book"],
        "subjects": [
            "a cupcake with swirled frosting and a cherry", "an ice cream cone with three scoops", "a stack of pancakes with syrup", "a donut with sprinkles",
            "a slice of layered cake", "a lollipop with a spiral", "a candy cane with a bow", "a cookie jar full of cookies",
            "a milkshake with a straw and whipped cream", "a tower of macarons", "a gingerbread house with candy trim", "a bowl of fruit",
            "a pie with a lattice crust", "a cup of hot chocolate with marshmallows", "a birthday cake with candles", "a popsicle melting slightly",
            "a jar of jelly beans", "a box of chocolates", "a waffle with strawberries", "a cotton candy cloud on a stick",
            "a pretzel with salt", "a slice of cherry pie on a plate", "a teapot with cupcakes", "a chocolate bar partly unwrapped",
            "a soft serve swirl in a cup", "a bakery display case", "a bowl of candy hearts", "a strawberry shortcake",
            "a muffin with blueberries", "a sundae in a tall glass",
        ],
    },
    "mandala": {
        "aliases": ["mandalas", "patterns", "geometric", "zen", "medallion", "kaleidoscope"],
        "noun": "Mandalas", "sub": "Mandala Designs",
        "keywords": ["mandala coloring book", "easy mandala coloring pages", "easy coloring book for adults", "bold and easy coloring book",
                     "large print coloring book", "relaxing coloring book", "coloring book for seniors"],
        "subjects": [
            "a mandala with eight large petals", "a circular pattern of hearts", "a sunburst mandala with wavy rays", "a mandala built from leaves",
            "a star-shaped mandala", "a mandala of round dots and rings", "a lotus mandala", "a mandala with crescent moons",
            "a snowflake mandala", "a mandala of seashells", "a flower-of-life pattern", "a mandala with butterflies",
            "a spiral medallion", "a mandala of teardrop shapes", "a mandala with a sun center", "a wreath mandala of berries",
            "a mandala of feathers", "a honeycomb mandala", "a mandala with arched windows", "a wave pattern mandala",
            "a mandala of raindrops", "a kaleidoscope of triangles", "a mandala of paisley shapes", "a mandala of fish",
            "a mandala of tulips", "a compass rose mandala", "a mandala of hearts and leaves", "a mandala with bells",
            "a clover mandala", "a mandala of stars and planets",
        ],
    },
    "christmas": {
        "aliases": ["xmas", "holiday", "winter holiday", "festive", "noel"],
        "noun": "Christmas", "sub": "Holiday Designs",
        "keywords": ["christmas coloring book", "holiday coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "christmas gifts for coloring", "large print coloring book", "winter coloring book"],
        "subjects": [
            "a decorated christmas tree with a star", "a stocking hung on a mantel", "a gingerbread house with icing", "a wreath with a big bow",
            "a reindeer with a bell collar", "a sleigh full of presents", "a candy cane with holly", "a pile of wrapped presents",
            "a mug of cocoa with a candy cane", "a christmas bell with ribbon", "a snow globe with a house inside", "a penguin in a scarf",
            "a cozy fireplace with stockings", "a striped ornament", "a polar bear with a gift", "a cardinal on a snowy branch",
            "a lantern in the snow", "a christmas pudding with holly", "a gift bag with tissue paper", "a toy train under a tree",
            "a star tree topper", "a pair of mittens with snowflakes", "a holly branch with berries", "a snowy church with a bell tower",
            "a cat tangled in lights", "a rocking horse with a bow", "a jingle bell garland", "a snowy cottage with smoke from the chimney",
            "a teddy bear in a knitted hat", "a mailbox full of cards in the snow",
        ],
    },
    "halloween": {
        "aliases": ["spooky", "pumpkins", "pumpkin", "autumn spooky", "trick or treat"],
        "noun": "Halloween", "sub": "Spooky Fun Designs",
        "keywords": ["halloween coloring book", "pumpkin coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "spooky coloring book", "large print coloring book", "autumn coloring book"],
        "subjects": [
            "a jack-o-lantern with a toothy grin", "a black cat arched on a fence", "a pointed hat with a buckle", "a cauldron with bubbles",
            "a bat flying past the moon", "a haunted house on a hill", "a spider in its web", "a pile of pumpkins",
            "a candy bucket overflowing", "an owl on a bare branch", "a trick-or-treat bag with candy", "a crow on a pumpkin",
            "a broomstick leaning on a fence", "a potion bottle with a cork", "a candy apple on a stick", "a wolf howling at the full moon",
            "a spooky tree with knotted branches", "a raven on a fence post", "a bat hanging upside down", "a cat in a pointed hat",
            "a spider on a pumpkin", "a candle in a lantern", "a toad on a mushroom", "a bowl of candy corn",
            "a creaky gate with a pumpkin", "a cat riding a broom", "a moon with bats and clouds", "a pumpkin patch with a fence",
            "a cobweb in a window frame", "a cauldron with a cat beside it",
        ],
    },
    "birds": {
        "aliases": ["bird", "garden birds", "owls", "parrots", "songbirds", "backyard birds"],
        "noun": "Birds", "sub": "Bird Designs",
        "keywords": ["bird coloring book", "birds coloring pages", "easy coloring book for adults", "bold and easy coloring book",
                     "large print coloring book", "relaxing coloring book", "coloring book for seniors"],
        "subjects": [
            "a robin on a branch", "an owl with wide eyes", "a hummingbird at a flower", "a flamingo standing on one leg",
            "a toucan with a big beak", "a peacock with a fanned tail", "a parrot on a perch", "a swan on a pond",
            "a penguin on ice", "a duck with ducklings", "a cardinal in the snow", "a bluebird singing on a fence",
            "a pelican on a post", "a chickadee on a feeder", "a woodpecker on a trunk", "an eagle soaring",
            "a dove with an olive branch", "a puffin with a fish", "a rooster crowing", "a goldfinch on a thistle",
            "a kingfisher diving", "a sparrow in a nest with eggs", "a heron in the reeds", "a pigeon on a rooftop",
            "a cockatoo with a crest", "a bird bath with two birds", "a stork standing in water", "a seagull on a pier post",
            "a quail with a plume", "a magpie with a shiny ring",
        ],
    },
    "butterflies": {
        "aliases": ["butterfly", "insects", "bugs", "bees", "ladybugs", "garden bugs"],
        "noun": "Butterflies and Bugs", "sub": "Butterfly Designs",
        "keywords": ["butterfly coloring book", "bugs coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "insects coloring book", "large print coloring book", "relaxing coloring book for adults"],
        "subjects": [
            "a butterfly with wide patterned wings", "a ladybug on a leaf", "a bee on a sunflower", "a dragonfly over a pond",
            "a snail with a spiral shell", "a caterpillar on a branch", "a grasshopper in tall grass", "a beetle with a round shell",
            "a moth near a lantern", "a butterfly mandala", "a beehive with bees", "an ant carrying a leaf",
            "a jar of fireflies", "a butterfly on a flower", "a cricket on a stone", "a spider web with dew drops",
            "a worm peeking from an apple", "a stag beetle", "a pair of butterflies", "a bumblebee in flight",
            "a cicada on tree bark", "a praying mantis on a stem", "a swallowtail butterfly", "a monarch butterfly on milkweed",
            "a butterfly garden with three blooms", "a ladybug family on a mushroom", "a water strider on a pond", "a bee with a honey pot",
            "a butterfly chrysalis on a branch", "a dragonfly mandala",
        ],
    },
    "cats": {
        "aliases": ["cat", "kittens", "kitten", "kitty"],
        "noun": "Cats", "sub": "Cat Designs",
        "keywords": ["cat coloring book", "kitten coloring pages", "easy coloring book for adults", "bold and easy coloring book",
                     "cute cats coloring book", "large print coloring book", "relaxing coloring book"],
        "subjects": [
            "a cat curled up asleep", "a kitten playing with yarn", "a cat in a window with plants", "a cat stretching on a rug",
            "a cat sitting in a box", "a cat with a bow tie", "a cat chasing a butterfly", "a cat on a bookshelf",
            "a kitten in a teacup", "a cat wearing a party hat", "a cat licking its paw", "a cat beside a fish bowl",
            "a cat under an umbrella", "a cat in a basket of flowers", "a cat on a fence at night", "a cat with a ball of wool",
            "a cat sleeping on a stack of books", "a cat peeking from a paper bag", "a cat on a windowsill with a moon", "a fluffy cat with a big tail",
            "a cat in a flower crown", "a cat beside a food bowl", "a cat with a mouse toy", "a cat on a scratching post",
            "a cat in a sweater", "a cat watching a fish", "a cat and a kitten nose to nose", "a cat with a crown",
            "a cat on a cushion", "a cat sitting in a planter",
        ],
    },
    "dogs": {
        "aliases": ["dog", "puppies", "puppy", "pups"],
        "noun": "Dogs", "sub": "Dog Designs",
        "keywords": ["dog coloring book", "puppy coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "cute dogs coloring book", "large print coloring book", "relaxing coloring book for adults"],
        "subjects": [
            "a puppy with a bone", "a dog chasing a ball", "a dog in a doghouse", "a dog catching a frisbee",
            "a dachshund in a hot dog bun", "a dog with floppy ears", "a pug with a bow", "a dog digging in a garden",
            "a dog with a bandana", "a dog in a bathtub with bubbles", "a dog on a skateboard", "a dog carrying a rolled newspaper",
            "a sleeping dog on a rug", "a corgi with a crown", "a dog with a birthday cake", "a dog in a sweater",
            "a dog with a tennis ball", "a dog on a beach with a shell", "a poodle with a bow", "a bulldog with a chew toy",
            "a dog in a wagon", "a husky in the snow", "a dog with a stick in a river", "a dog in a basket of flowers",
            "a dog peeking from a blanket", "a dog with a big bowl", "a dog surrounded by butterflies", "a golden retriever with a ball",
            "a dog and a cat sleeping together", "a dog in a party hat",
        ],
    },
    "fruits": {
        "aliases": ["fruit", "vegetables", "veggies", "produce", "fruits and vegetables", "harvest"],
        "noun": "Fruits and Vegetables", "sub": "Fruit and Veggie Designs",
        "keywords": ["fruits coloring book", "vegetables coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "toddler coloring book food", "large print coloring book", "healthy food coloring book"],
        "subjects": [
            "a bunch of grapes with leaves", "a smiling strawberry", "a pineapple with a leafy crown", "a watermelon slice",
            "an apple with a leaf", "a pear on a branch", "a bunch of bananas", "an orange cut in half",
            "a carrot with a leafy top", "a pumpkin with vines", "a tomato on a vine", "a corn cob with husk",
            "a bowl of cherries", "a lemon with blossoms", "three bell peppers", "a basket of apples",
            "a peach with a leaf", "an avocado cut in half", "a bunch of broccoli", "two mushrooms",
            "a pea pod with peas", "a bunch of radishes", "a sliced kiwi", "a coconut with a palm leaf",
            "a pair of cherries", "an eggplant with a leaf", "a bowl of mixed fruit", "a berry branch",
            "a pile of pumpkins and squash", "a wooden crate of fruit",
        ],
    },
    "safari": {
        "aliases": ["jungle", "zoo", "wild animals", "africa", "savanna", "zoo animals", "jungle animals"],
        "noun": "Safari Animals", "sub": "Safari Friends",
        "keywords": ["safari animals coloring book", "jungle animals coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "zoo animals coloring book", "large print coloring book", "cute animals coloring book"],
        "subjects": [
            "a lion with a big mane", "an elephant spraying water", "a giraffe eating leaves", "a zebra with bold stripes",
            "a hippo in a river", "a rhino under a tree", "a monkey hanging from a vine", "a cheetah on a rock",
            "a meerkat standing guard", "a crocodile smiling in the water", "a pair of flamingos", "a toucan on a branch",
            "a gorilla eating a banana", "a leopard in a tree", "a warthog in the grass", "a baby elephant with its mother",
            "an ostrich with fluffy feathers", "a chameleon on a branch", "a parrot in jungle leaves", "a baobab tree at sunset",
            "a tortoise walking", "a koala in a eucalyptus tree", "a kangaroo with a joey", "a panda with bamboo",
            "a sloth hanging from a branch", "a tiger among big leaves", "a camel in the desert", "a laughing hyena",
            "a wildebeest in tall grass", "a safari jeep parked under a tree",
        ],
    },
    "unicorns": {
        "aliases": ["unicorn", "fantasy", "magical", "rainbows", "rainbow", "dragons", "dragon"],
        "noun": "Unicorns and Rainbows", "sub": "Magical Designs",
        "keywords": ["unicorn coloring book", "rainbow coloring pages", "easy coloring book for kids", "bold and easy coloring book",
                     "magical coloring book", "large print coloring book", "cute unicorn coloring book"],
        "subjects": [
            "a unicorn with a flowing mane", "a rainbow with clouds", "a unicorn under a rainbow", "a castle on a cloud",
            "a dragon with small wings", "a unicorn cupcake", "a magic wand with stars", "a crystal ball on a stand",
            "a rainbow with hearts", "a unicorn sleeping on a cloud", "a treasure chest with gems", "a pegasus flying",
            "a unicorn in a flower meadow", "a crown with jewels", "a shooting star trail", "a unicorn ice cream cone",
            "a baby dragon hatching", "a potion bottle with hearts", "a rainbow waterfall", "a unicorn with a party hat",
            "a mushroom house", "a unicorn mandala", "a butterfly with heart-shaped wings", "a hot air balloon with stars",
            "a unicorn kite", "a rainbow bridge", "a cluster of sparkly gems", "a unicorn beside a rainbow slide",
            "a magic book with stars on the cover", "a cloud with a smiling moon",
        ],
    },
    "mushrooms": {
        "aliases": ["mushroom", "cottagecore", "cozy", "toadstools", "toadstool", "fungi"],
        "noun": "Cozy Mushrooms", "sub": "Cottagecore Designs",
        "keywords": ["mushroom coloring book", "cottagecore coloring pages", "easy coloring book for adults", "bold and easy coloring book",
                     "large print coloring book", "relaxing coloring book", "cozy coloring book"],
        "subjects": [
            "a spotted mushroom with a snail", "a cluster of three mushrooms", "a mushroom house with a round door", "a toadstool under a fern",
            "a mushroom with a ladybug", "a basket of mushrooms", "a mushroom lantern", "a frog on a mushroom",
            "a mushroom mandala", "a mushroom with a tiny window and chimney", "a ring of mushrooms in the grass", "a mushroom and acorns",
            "a mushroom teapot", "a mushroom in moss with pebbles", "a mushroom village", "a mushroom with dew drops",
            "a mushroom under a crescent moon", "a mushroom with a mouse", "a mushroom garden with a fence", "a mushroom in a jar",
            "a mushroom patch with flowers", "a mushroom with a hedgehog", "a mushroom umbrella over a snail", "a mushroom cottage with a path",
            "a mushroom with a mailbox", "a mushroom with a bird on top", "a mushroom and a watering can", "a mushroom wreath",
            "a tall thin mushroom and a short wide one", "a mushroom in a teacup",
        ],
    },
    "cottages": {
        "aliases": ["houses", "house", "cottage", "cozy homes", "village", "buildings", "cityscape", "town"],
        "noun": "Cozy Cottages", "sub": "Cottage Designs",
        "keywords": ["cottage coloring book", "houses coloring pages", "easy coloring book for adults", "bold and easy coloring book",
                     "large print coloring book", "relaxing coloring book", "coloring book for seniors"],
        "subjects": [
            "a cottage with a thatched roof", "a lighthouse by the sea", "a windmill with wide sails", "a treehouse with a ladder",
            "a beach hut on stilts", "a castle with two towers", "a barn with a silo", "a cabin in the woods",
            "a greenhouse full of plants", "a bakery with a striped awning", "a village street with three houses", "a church with a bell tower",
            "a houseboat on a river", "a gingerbread cottage", "a mountain chalet", "a tiny home on wheels",
            "a mailbox with flowers", "a garden shed with tools", "a water tower", "a town hall with arched windows",
            "a farmhouse with a porch", "a pagoda by a pond", "a round dome house", "a cottage door with a wreath",
            "a bridge over a stream", "a well with a bucket", "a fence with a gate and flowers", "a birdhouse on a pole",
            "a picnic table under a tree", "a cozy cottage in the snow",
        ],
    },
}


def _names() -> dict[str, str]:
    out: dict[str, str] = {}
    for key, rec in THEMES.items():
        out[key] = key
        for alias in rec["aliases"]:
            out[alias] = key
    return out


def find_theme(text: str) -> dict | None:
    """The library theme that best matches free text: an alias found as a whole word first (longest alias
    wins), then a fuzzy match per word so 'ocenan' still lands on ocean. None when nothing fits."""
    t = re.sub(r"[^a-z0-9 ]+", " ", (text or "").lower())
    if not t.strip():
        return None
    names = _names()
    for alias in sorted(names, key=len, reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", t):
            return {**THEMES[names[alias]], "key": names[alias]}
    words = [w for w in t.split() if len(w) >= 4 and w not in STYLE_WORDS]
    for w in words:
        hit = difflib.get_close_matches(w, list(names), n=1, cutoff=0.8)
        if hit:
            return {**THEMES[names[hit[0]]], "key": names[hit[0]]}
    return None
