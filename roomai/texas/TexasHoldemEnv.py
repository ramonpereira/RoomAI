#!/bin/python
#coding:utf-8

import random
import copy
import roomai.common
import roomai
import logging

from roomai.common import Info

from roomai.texas.TexasHoldemUtil import *
from roomai.texas.TexasHoldemAction import *
from roomai.texas.TexasHoldemInfo import *
from functools                    import cmp_to_key


class TexasHoldemEnv(roomai.common.AbstractEnv):
    """
    """

    @classmethod
    def __check_initialization_configuration__(cls, env):
        if len(env.chips) != env.num_players:
            raise ValueError("len(env.chips)%d != env.num_players%d" % (len(env.chips), env.num_players))

        if env.num_players * 7 > 52:
            raise ValueError("env.num_players * 5 must be less than 51, now env.num_players = %d" % (env.num_players))

        return True

    #@override
    def init(self, params = dict()):
        '''
        initialize the game env
        
        :param params:  parameters of the game
        :return: infos, public_state, person_states, private_state
        '''
        self.logger         = roomai.get_logger()

        if "num_players" in params:
            self.num_players = params["num_players"]
        else:
            self.num_players = 3

        if "dealer_id" in params:
            self.dealer_id = params["dealer_id"]
        else:
            self.dealer_id = int(random.random() * self.num_players)

        if "chips" in params:
            self.chips     = params["chips"]
        else:
            self.chips     = [1000 for i in range(self.num_players)]

        if "big_blind_bet" in params:
            self.big_blind_bet = params["big_blind_bet"]
        else:
            self.big_blind_bet = 10

        if "allcards" in params:
            self.allcards = [c.__deepcopy__() for c in params["allcards"]]
        else:
            self.allcards = list(roomai.common.AllPokerCards_Without_King.values())
            random.shuffle(self.allcards)

        if "record_history" in params:
            self.record_history = params["record_history"]
        else:
            self.record_history = False


        self.__check_initialization_configuration__(self)


        ## public info
        small = (self.dealer_id + 1) % self.num_players
        big   = (self.dealer_id + 2) % self.num_players

        self.public_state        = TexasHoldemPublicState()
        pu                       = self.public_state
        pu.num_players           = self.num_players
        pu.dealer_id             = self.dealer_id
        pu.big_blind_bet         = self.big_blind_bet
        pu.raise_account         = self.big_blind_bet

        pu.is_fold               = [False for i in range(self.num_players)]
        pu.num_quit              = 0
        pu.is_allin              = [False for i in range(self.num_players)]
        pu.num_allin             = 0
        pu.is_needed_to_action   = [True for i in range(self.num_players)]
        pu.num_needed_to_action  = pu.num_players

        pu.bets                  = [0 for i in range(self.num_players)]
        pu.chips                 = self.chips
        pu.stage                 = StageSpace.firstStage
        pu.turn                  = (big+1)%pu.num_players
        pu.public_cards          = []

        pu.previous_id           = None
        pu.previous_action       = None

        if pu.chips[big] > self.big_blind_bet:
            pu.chips[big] -= self.big_blind_bet
            pu.bets[big]  += self.big_blind_bet
        else:
            pu.bets[big]     = pu.chips[big]
            pu.chips[big]    = 0
            pu.is_allin[big] = True
            pu.num_allin    += 1
        pu.max_bet_sofar     = pu.bets[big]
        pu.raise_account = self.big_blind_bet

        if pu.chips[small] > self.big_blind_bet / 2:
            pu.chips[small] -= self.big_blind_bet /2
            pu.bets[small]  += self.big_blind_bet /2
        else:
            pu.bets[small]     = pu.chips[small]
            pu.chips[small]    = 0
            pu.is_allin[small] = True
            pu.num_allin      += 1

        pu.is_terminal         = False
        pu.scores              = None

        # private info
        self.private_state = TexasHoldemPrivateState()
        pr                 = self.private_state
        pr.keep_cards      = self.allcards[self.num_players*2:self.num_players*2+5]

        ## person info
        self.person_states    = [TexasHoldemPersonState() for i in range(self.num_players)]
        pes                   = self.person_states
        for i in range(self.num_players):
            pes[i].id = i
            pes[i].hand_cards = self.allcards[i*2:(i+1)*2]
        pes[pu.turn].available_actions = self.available_actions(pu, pes[pu.turn])

        self.__gen_history__()
        infos = self.__gen_infos__()

        if self.logger.level <= logging.DEBUG:
            self.logger.debug("TexasHoldemEnv.init: num_players = %d, dealer_id = %d, chip = %d, big_blind_bet = %d"%(\
                pu.num_players,\
                pu.dealer_id,\
                pu.chips[0],\
                pu.big_blind_bet
            ))

        return infos, pu, pes, pr

    ## we need ensure the action is valid
    #@Overide
    def forward(self, action):
        '''
        forward the TexasHoldem game with the action taken by the current player
        
        :param action: The action taken by the current player 
        '''
        pu         = self.public_state
        pe         = self.person_states
        pr         = self.private_state

        if not self.is_action_valid(action, pu, pe[pu.turn]):
            self.logger.critical("action=%s is invalid" % (action.key()))
            raise ValueError("action=%s is invalid" % (action.key()))


        if action.option() == TexasHoldemAction.Fold:
            self.__action_fold__(action)
        elif action.option() == TexasHoldemAction.Check:
            self.__action_check__(action)
        elif action.option() == TexasHoldemAction.Call:
            self.__action_call__(action)
        elif action.option() == TexasHoldemAction.Raise:
            self.__action_raise__(action)
        elif action.option() == TexasHoldemAction.AllIn:
            self.__action_allin__(action)
        else:
            raise Exception("action.option(%s) not in [Fold, Check, Call, Raise, AllIn]"%(action.option()))
        pu.previous_id     = pu.turn
        pu.previous_action = action
        pu.is_terminal     = False
        pu.scores          = None

        # computing_score
        if TexasHoldemEnv.__is_compute_scores__(self.public_state):
            ## need showdown
            pu.public_cards = pr.keep_cards[0:5]
            pu.is_terminal  = True
            pu.scores       = self.compute_scores()
            pe[pu.previous_id].available_actions = dict()

        # enter into the next stage
        elif TexasHoldemEnv.__is_nextround__(self.public_state):
            add_cards = []
            if pu.stage == StageSpace.firstStage:   add_cards = pr.keep_cards[0:3]
            if pu.stage == StageSpace.secondStage:  add_cards = [pr.keep_cards[3]]
            if pu.stage == StageSpace.thirdStage:   add_cards = [pr.keep_cards[4]]

            pu.public_cards.extend(add_cards)
            pu.stage                      = pu.stage + 1

            pu.num_needed_to_action       = 0
            pu.is_needed_to_action        = [False for i in range(pu.num_players)]
            for i in range(pu.num_players):
                if pu.is_fold[i] != True and pu.is_allin[i] != True:
                    pu.is_needed_to_action[i]      = True
                    pu.num_needed_to_action       += 1

            pu.turn                                             = pu.dealer_id
            pu.turn                                             = self.__next_player__(pu)
            pe[self.public_state.previous_id].available_actions = dict()
            pe[self.public_state.turn].available_actions        = self.available_actions(self.public_state, self.person_states[self.public_state.turn])

        ##normal
        else:
            pu.turn                                                             = self.__next_player__(pu)
            self.person_states[self.public_state.previous_id].available_actions = dict()
            self.person_states[self.public_state.turn].available_actions        = self.available_actions(self.public_state, self.person_states[self.public_state.turn])


        if self.logger.level <= logging.DEBUG:
            self.logger.debug("TexasHoldemEnv.forward: num_quit+num_allin = %d+%d = %d, action = %s, stage = %d"%(\
                self.public_state.num_quit,\
                self.public_state.num_allin,\
                self.public_state.num_quit + self.public_state.num_allin,\
                action.key,\
                self.public_state.stage\
            ))

        self.__gen_history__()
        infos = self.__gen_infos__()
        return infos, self.public_state, self.person_states, self.private_state

    #override
    @classmethod
    def compete(cls, env, players):
        '''
        Hold a competes for players with this env
        
        :param env: The TaxasHoldem game environment
        :param players: a list of AI players 
        :return: scores for these players
        '''

        total_scores       = [0 for i in range(len(players))]
        total_count        = 1000


        for count in range(total_count):

            chips          = [(1000 + int(random.random() * 200)) for i in range(len(players))]
            num_players    = len(players)
            dealer_id      = int(random.random() * len(players))
            big_blind_bet  = 50

            infos, public, persons, private = env.init({"chips":chips,
                                                        "num_players":num_players,
                                                        "dealer_id":dealer_id,
                                                        "big_blind_bet":big_blind_bet})
            for i in range(len(players)):
                players[i].receive_info(infos[i])
            while public.is_terminal == False:
                turn = public.turn
                action = players[turn].take_action()
                #print len(infos[turn].person_state.available_actions),action.key(),turn
                infos, public, persons, private = env.forward(action)
                for i in range(len(players)):
                    players[i].receive_info(infos[i])

            for i in range(len(players)):
                players[i].receive_info(infos[i])
                total_scores[i] += public.scores[i]


            if (count + 1)%500 == 0:
                tmp_scores = [0 for i in range(len(total_scores))]
                for i in range(len(total_scores)):
                    tmp_scores[i] = total_scores[i] / (count+1)
                roomai.get_logger().info("TexasHoldem completes %d competitions, scores=%s"%(count+1, ",".join([str(i) for i in tmp_scores])))

        for i in range(len(total_scores)):
            total_scores[i] /= 1.0 * total_count

        return total_scores


    def compute_scores(self):
        '''
        compute scores at the end of the game
        
        :return: scores for the players
        '''

        pu  = self.public_state
        pes = self.person_states
        pr  = self.private_state

        ## compute score before showdown, the winner takes all
        if pu.num_players  ==  pu.num_quit + 1:
            scores = [0 for i in range(pu.num_players)]
            for i in range(pu.num_players):
                if pu.is_fold[i] == False:
                    scores[i] = sum(pu.bets)
                    break

        ## compute score after showdown
        else:
            scores                = [0 for i in range(pu.num_players)]
            playerid_pattern_bets = [] #for not_quit players
            for i in range(pu.num_players):
                if pu.is_fold[i] == True: continue
                hand_pattern_cards = self.__cards2pattern_cards__(pes[i].hand_cards, pr.keep_cards)
                playerid_pattern_bets.append((i,hand_pattern_cards,pu.bets[i]))

            for playerid_pattern_bet in playerid_pattern_bets:
                if len(playerid_pattern_bet[1][1]) < 5:
                    i = 0

            playerid_pattern_bets.sort(key=lambda x:self.__compute_rank_pattern_cards__(x[1]))

            pot_line = 0
            previous = None
            tmp_playerid_pattern_bets      = []
            for i in range(len(playerid_pattern_bets)-1,-1,-1):
                if previous == None:
                    tmp_playerid_pattern_bets.append(playerid_pattern_bets[i])
                    previous = playerid_pattern_bets[i]
                elif self.__compare_patterns_cards__(playerid_pattern_bets[i][1], previous[1]) == 0:
                    tmp_playerid_pattern_bets.append(playerid_pattern_bets[i])
                    previous = playerid_pattern_bets[i]
                else:
                    tmp_playerid_pattern_bets.sort(key = lambda x:x[2])
                    for k in range(len(tmp_playerid_pattern_bets)):
                        num1          = len(tmp_playerid_pattern_bets) - k
                        sum1          = 0
                        max_win_score = pu.bets[tmp_playerid_pattern_bets[k][0]]
                        for p in range(pu.num_players):
                            sum1      += min(max(0, pu.bets[p] - pot_line), max_win_score)
                        for p in range(k, len(tmp_playerid_pattern_bets)):
                            scores[tmp_playerid_pattern_bets[p][0]] += sum1 / num1
                        scores[pu.dealer_id] += sum1 % num1
                        if pot_line <= max_win_score:
                            pot_line = max_win_score
                    tmp_playerid_pattern_bets = []
                    tmp_playerid_pattern_bets.append(playerid_pattern_bets[i])
                    previous = playerid_pattern_bets[i]


            if len(tmp_playerid_pattern_bets) > 0:
                tmp_playerid_pattern_bets.sort(key = lambda  x:x[2])
                for i in range(len(tmp_playerid_pattern_bets)):
                    num1 = len(tmp_playerid_pattern_bets) - i
                    sum1 = 0
                    max_win_score = pu.bets[tmp_playerid_pattern_bets[i][0]]
                    for p in range(pu.num_players):
                        sum1 += min(max(0, pu.bets[p] - pot_line), max_win_score)
                    for p in range(i, len(tmp_playerid_pattern_bets)):
                        scores[tmp_playerid_pattern_bets[p][0]] += sum1 / num1
                    scores[pu.dealer_id] += sum1 % num1
                    if pot_line <= max_win_score: pot_line = max_win_score

        for p in range(pu.num_players):
            pu.chips[p] += scores[p]
            scores[p]   -= pu.bets[p]
        for p in range(pu.num_players):
            scores[p]   /= pu.big_blind_bet * 1.0
        return scores


    def __action_fold__(self, action):
        pu = self.public_state
        pu.is_fold[pu.turn]             = True
        pu.num_quit                    += 1

        pu.is_needed_to_action[pu.turn] = False
        pu.num_needed_to_action        -= 1

    def __action_check__(self, action):
        pu = self.public_state
        pu.is_needed_to_action[pu.turn] = False
        pu.num_needed_to_action        -= 1

    def __action_call__(self, action):
        pu = self.public_state
        pu.chips[pu.turn] -= action.price()
        pu.bets[pu.turn]  += action.price()
        pu.is_needed_to_action[pu.turn] = False
        pu.num_needed_to_action        -= 1

    def __action_raise__(self, action):
        pu = self.public_state


        pu.raise_account   = action.price() + pu.bets[pu.turn] - pu.max_bet_sofar
        pu.chips[pu.turn] -= action.price()
        pu.bets[pu.turn]  += action.price()
        pu.max_bet_sofar   = pu.bets[pu.turn]

        pu.is_needed_to_action[pu.turn] = False
        pu.num_needed_to_action        -= 1
        p = (pu.turn + 1)%pu.num_players
        while p != pu.turn:
            if pu.is_allin[p] == False and pu.is_fold[p] == False and pu.is_needed_to_action[p] == False:
                pu.num_needed_to_action   += 1
                pu.is_needed_to_action[p]  = True
            p = (p + 1) % pu.num_players


    def __action_allin__(self, action):
        pu = self.public_state

        pu.is_allin[pu.turn]   = True
        pu.num_allin          += 1

        pu.bets[pu.turn]      += action.price()
        pu.chips[pu.turn]      = 0

        pu.is_needed_to_action[pu.turn] = False
        pu.num_needed_to_action        -= 1
        if pu.bets[pu.turn] > pu.max_bet_sofar:
            pu.max_bet_sofar = pu.bets[pu.turn]
            p = (pu.turn + 1) % pu.num_players
            while p != pu.turn:
                if pu.is_allin[p] == False and pu.is_fold[p] == False and pu.is_needed_to_action[p] == False:
                    pu.num_needed_to_action  += 1
                    pu.is_needed_to_action[p] = True
                p = (p + 1) % pu.num_players

            pu.max_bet_sofar = pu.bets[pu.turn]

#####################################Utils Function ##############################

    @classmethod
    def __next_player__(self, pu):
        i = pu.turn
        if pu.num_needed_to_action == 0:
            return -1

        p = (i+1)%pu.num_players
        while pu.is_needed_to_action[p] == False:
            p = (p+1)%pu.num_players
        return p

    @classmethod
    def __is_compute_scores__(self, pu):
        '''
        :return: 
        A boolean variable indicates whether is it time to compute scores
        '''

        if pu.num_players == pu.num_quit + 1:
            return True

        # below need showdown

        if pu.num_players <=  pu.num_quit + pu.num_allin +1 and pu.num_needed_to_action == 0:
            return True

        if pu.stage == StageSpace.fourthStage and self.__is_nextround__(pu):
            return True

        return False

    @classmethod
    def __is_nextround__(self, public_state):
        '''
        
        :return: A boolean variable indicates whether is it time to enter the next stage
        '''
        return public_state.num_needed_to_action == 0

    @classmethod
    def __cards2pattern_cards__(cls, hand_cards, remaining_cards):
        key = cmp_to_key(roomai.common.PokerCard.compare)
        pointrank2cards = dict()
        for c in hand_cards + remaining_cards:
            if c.point_rank in pointrank2cards:
                pointrank2cards[c.point_rank].append(c)
            else:
                pointrank2cards[c.point_rank] = [c]
        for p in pointrank2cards:
            pointrank2cards[p].sort(key = key)

        suitrank2cards = dict()
        for c in hand_cards + remaining_cards:
            if c.suit_rank in suitrank2cards:
                suitrank2cards[c.suit_rank].append(c)
            else:
                suitrank2cards[c.suit_rank] = [c]
        for s in suitrank2cards:
            suitrank2cards[s].sort(key=key)

        num2point = [[], [], [], [], []]
        for p in pointrank2cards:
            num = len(pointrank2cards[p])
            num2point[num].append(p)
        for i in range(5):
            num2point[num].sort()

        sorted_point = []
        for p in pointrank2cards:
            sorted_point.append(p)
        sorted_point.sort()

        ##straight_samesuit
        for s in suitrank2cards:
            if len(suitrank2cards[s]) >= 5:
                numStraight = 1
                for i in range(len(suitrank2cards[s]) - 2, -1, -1):
                    if suitrank2cards[s][i].point_rank == suitrank2cards[s][i + 1].point_rank - 1:
                        numStraight += 1
                    else:
                        numStraight = 1

                    if numStraight == 5:
                        pattern = AllCardsPattern["Straight_SameSuit"]
                        return (pattern,suitrank2cards[s][i:i + 5])

        ##4_1
        if len(num2point[4]) > 0:
            p4 = num2point[4][0]
            p1 = -1
            for i in range(len(sorted_point) - 1, -1, -1):
                if sorted_point[i] != p4:
                    p1 = sorted_point[i]
                    break
            pattern = AllCardsPattern["4_1"]
            cards   = pointrank2cards[p4][0:4]
            cards.append(pointrank2cards[p1][0])

            return (pattern,cards)

        ##3_2
        if len(num2point[3]) >= 1:
            pattern = AllCardsPattern["3_2"]

            if len(num2point[3]) == 2:
                p3 = num2point[3][1]
                cards = pointrank2cards[p3][0:3]
                p2 = num2point[3][0]
                cards.append(pointrank2cards[p2][0])
                cards.append(pointrank2cards[p2][1])
                return (pattern,cards)

            if len(num2point[2]) >= 1:
                p3 = num2point[3][0]
                cards = pointrank2cards[p3][0:3]
                p2 = num2point[2][len(num2point[2]) - 1]
                cards.append(pointrank2cards[p2][0])
                cards.append(pointrank2cards[p2][1])
                return (pattern,cards)

        ##SameSuit
        for s in suitrank2cards:
            if len(suitrank2cards[s]) >= 5:
                pattern = AllCardsPattern["SameSuit"]
                len1 = len(suitrank2cards[s])
                cards = suitrank2cards[s][len1 - 5:len1]
                return (pattern,cards)

        ##Straight_DiffSuit
        numStraight = 1
        for idx in range(len(sorted_point) - 2, -1, -1):
            if sorted_point[idx] + 1 == sorted_point[idx]:
                numStraight += 1
            else:
                numStraight = 1

            if numStraight == 5:
                pattern = AllCardsPattern["Straight_DiffSuit"]
                cards = []
                for p in range(idx, idx + 5):
                    point = sorted_point[p]
                    cards.append(pointrank2cards[point][0])
                return (pattern,cards)

        ##3_1_1
        if len(num2point[3]) == 1:
            pattern = AllCardsPattern["3_1_1"]

            p3 = num2point[3][0]
            cards = pointrank2cards[p3][0:3]

            num = 0
            for i in range(len(sorted_point) - 1, -1, -1):
                p = sorted_point[i]
                if p != p3:
                    cards.append(pointrank2cards[p][0])
                    num += 1
                if num == 2:    break
            return (pattern,cards)

        ##2_2_1
        if len(num2point[2]) >= 2:
            pattern = AllCardsPattern["2_2_1"]
            p21 = num2point[2][len(num2point[2]) - 1]
            cards = []
            for c in pointrank2cards[p21]:
                cards.append(c)
            p22 = num2point[2][len(num2point[2]) - 2]
            for c in pointrank2cards[p22]:
                cards.append(c)

            flag = False
            for i in range(len(sorted_point) - 1, -1, -1):
                p = sorted_point[i]
                if p != p21 and p != p22:
                    c = pointrank2cards[p][0]
                    cards.append(c)
                    flag = True
                if flag == True:    break;
            return (pattern,cards)

        ##2_1_1_1
        if len(num2point[2]) == 1:
            pattern = AllCardsPattern["2_1_1_1"]
            p2 = num2point[2][0]
            cards = pointrank2cards[p2][0:2]
            num = 0
            for p in range(len(sorted_point) - 1, -1, -1):
                p1 = sorted_point[p]
                if p1 != p2:
                    cards.append(pointrank2cards[p1][0])
                if num == 3:    break
            return (pattern,cards)

        ##1_1_1_1_1
        pattern = AllCardsPattern["1_1_1_1_1"]
        count = 0
        cards = []
        for i in range(len(sorted_point) - 1, -1, -1):
            p = sorted_point[i]
            for c in pointrank2cards[p]:
                cards.append(c)
                count += 1
                if count == 5: break
            if count == 5: break
        return (pattern,cards)

    @classmethod
    def __compare_handcards__(cls, hand_card0, hand_card1, keep_cards):

        pattern0 = TexasHoldemEnv.__cards2pattern_cards__(hand_card0, keep_cards)
        pattern1 = TexasHoldemEnv.__cards2pattern_cards__(hand_card1, keep_cards)

        diff = cls.__compare_patterns_cards__(pattern0, pattern1)
        return diff

    @classmethod
    def __compute_rank_pattern_cards__(cls, pattern_cards):
        rank = pattern_cards[0][5] * 1000
        for i in range(5):
            rank *= 1000
            rank += pattern_cards[1][i].point_rank
        return rank

    @classmethod
    def __compare_patterns_cards__(cls, p1, p2):
        return cls.__compute_rank_pattern_cards__(p1) - cls.__compute_rank_pattern_cards__(p2)

    @classmethod
    def available_actions(cls, public_state, person_state):
        '''
        generate all available(valid) actions
        
        :param public_state:  public_state of the TexasHoldem game
        :param person_state:  person_state w.r.t to the current player
        :return: all available(valid) actions
        '''

        pu = public_state
        pe = person_state
        turn = pu.turn
        key_actions = dict()

        if pu.is_allin[turn] == True or pu.is_fold[turn] == True:
            return
        if pu.chips[turn] == 0:
            return



        ## for fold
        action = TexasHoldemAction.lookup(TexasHoldemAction.Fold + "_0")
        #if cls.is_action_valid(action,public_state, person_state):
        key_actions[action.key()] = action

        ## for check
        if pu.bets[turn] == pu.max_bet_sofar:
            action = TexasHoldemAction.lookup(TexasHoldemAction.Check + "_0")
            #if cls.is_action_valid(action, public_state, person_state):
            key_actions[action.key()] = action

        ## for call
        if pu.bets[turn] != pu.max_bet_sofar and pu.chips[turn] > pu.max_bet_sofar - pu.bets[turn]:
            action = TexasHoldemAction.lookup(TexasHoldemAction.Call + "_%d" % (pu.max_bet_sofar - pu.bets[turn]))
            #if cls.is_action_valid(action, public_state, person_state):
            key_actions[action.key()] = action

        ## for raise
        #if pu.bets[turn] != pu.max_bet_sofar and \
        if pu.chips[turn] > pu.max_bet_sofar - pu.bets[turn] + pu.raise_account:
            num = int((pu.chips[turn] - (pu.max_bet_sofar - pu.bets[turn])) / pu.raise_account)
            for i in range(1, num + 1):
                price = pu.max_bet_sofar - pu.bets[turn] + pu.raise_account * i
                if price == pu.chips[pu.turn]:  continue
                action = TexasHoldemAction.lookup(TexasHoldemAction.Raise + "_%d" % (price))
                #if cls.is_action_valid(action, public_state, person_state):
                key_actions[action.key()] = action

        ## for all in
        action = TexasHoldemAction.lookup(TexasHoldemAction.AllIn + "_%d" % (pu.chips[turn]))
        #if cls.is_action_valid(action, public_state, person_state):
        key_actions[action.key()] = action

        return key_actions

    @classmethod
    def is_action_valid(cls, action, public_state, person_state):
        '''
        is the action valid

        :param action: the action to judge
        :param public_state:  public_state of the TexasHoldem game
        :param person_state:  person_state w.r.t to the current player
        :return: a boolean variable indicating whether the action is valid
        '''

        return action.key() in person_state.available_actions

