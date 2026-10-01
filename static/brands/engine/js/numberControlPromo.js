
function createPromoNumberPicker(ticketCount,preSelectedNumbers){
	var numberShow ='';
	var index = '';
	var i =1;
	//init ticket display number 
	for ( i = 1; i <= settings.PickBallNumber; i++){
		index = settings.stringTags.showNumber +'1_' + i;
		numberShow = '<span class="ticketNumber" id='+ index + '></span>';
		$('#choosenNumber').append(numberShow);
	}	
	//init select ticket number
	for ( i = 1; i <= settings.MaxBallNumber; i++){
		index = 'ticketNumber_1_' + i;
		numberShow = '<li class="ticketNumber" id='+ index + '  onClick="addNumber(this.id)">' + i +'</li>';
		$('#availableNumbers_1').append(numberShow);
	}
	//init bonus display number 
	for ( i = 1; i <= settings.BonusBallNumber; i++){
		index = settings.stringTags.showBonus +'1_' + i;
		numberShow = '<span class="bonusTicketNumber choosenBonus" id ='+ index + '></span>';
		$('#choosenNumber').append(numberShow);
	}	
	//init select bonus  number
	for ( i = 1; i <= settings.MaxBonusBallNumber; i++){
		index = 'bonusTicketNumber_1_' + i;
		numberShow = '<li class="bonusTicketNumber" id='+ index + '  onClick="addNumber(this.id)">' + i +'</li>';
		$('#availableBonusNumbers_1').append(numberShow);
	}
	// template 
	$('#lines_1').clone().attr('id', 'template').hide().appendTo("#tickets_section");
	settings.tickets.push(1);
	if(sessionTicketNumbers != ''){
		sessionSavedPromoTicket();
	} else {
		if(preSelectedNumbers == true){
			quickPickExceptPreselected('#quickPick_1');
		} else {
			quickPick('#quickPick_1');
		}
		addline(ticketCount,preSelectedNumbers);
	}
}

function sessionSavedPromoTicket(){
	savedTicketLength = sessionTicketNumbers.length;
	savedTicketNumbersLength = sessionTicketNumbers[0].Numbers.length;
	savedTicketBonusNumbersLength = sessionTicketNumbers[0].BonusNumbers.length;
	for(var x=0;x<savedTicketLength;x++){
		if(x > 0){
			addline(1);
		}
		var ticketNumber = x+1;
		for(var y=0;y<savedTicketNumbersLength;y++){
			addNumber('ticketNumber_'+ticketNumber+'_'+sessionTicketNumbers[x].Numbers[y]);
		}
		for(var z=0;z<savedTicketBonusNumbersLength;z++){
			addNumber('bonusTicketNumber_'+ticketNumber+'_'+sessionTicketNumbers[x].BonusNumbers[z]);
		}
	}
}
 
function addline(ticketCount,preSelectedNumbers){
	for(x=0;x<ticketCount;x++){
		var $boardSection = $('div[id^="lines_"]:last'); // get the last DIV where ID starts with ^= "ticket_"
		var ticketIndex = parseInt($boardSection.prop("id").match(/\d+/g), 10 ) +1; // Read the Number from that DIV's ID (i.e: 3 from "board_3") then increment that number by 1
		$('#template').clone().attr('id', 'lines_'+ ticketIndex).show().appendTo("#tickets_section");
		$('#lines_' + ticketIndex).find("#clear_1").attr("id","clear_" + ticketIndex);
		$('#lines_' + ticketIndex).find("#quickPick_1").attr("id","quickPick_" + ticketIndex);
		$('#lines_' + ticketIndex).find("#ticket_1").attr("id","ticket_" + ticketIndex);
		$('#lines_' + ticketIndex).find("#complete_1").attr("id","complete_" + ticketIndex);
		$('#lines_' + ticketIndex).find("#incomplete_1").attr("id","incomplete_" + ticketIndex);
		$('#lines_' + ticketIndex).find("#availableNumbers_1").attr("id","availableNumbers_" + ticketIndex);
		$('#lines_' + ticketIndex).find("#availableBonusNumbers_1").attr("id","availableBonusNumbers_" + ticketIndex);
		for(var i=1;i<=settings.PickBallNumber;i++){
			$('#lines_' + ticketIndex).find("#showNumber_" + 1 + "_" + i).attr("id","showNumber_" + ticketIndex + "_" + i);
		}
		for(var j=1;j<=settings.BonusBallNumber;j++){
			$('#lines_' + ticketIndex).find("#showBonus_" + 1 + "_" + j).attr("id","showBonus_" + ticketIndex + "_" + j);
		}
		for(var y=1;y<=settings.MaxBallNumber;y++){
			$('#lines_' + ticketIndex).find("#ticketNumber_" + 1 + "_" + y).attr("id","ticketNumber_" + ticketIndex + "_" + y);
		}
		for(var z=1;z<=settings.MaxBonusBallNumber;z++){
			$('#lines_' + ticketIndex).find("#bonusTicketNumber_" + 1 + "_" + z).attr("id","bonusTicketNumber_" + ticketIndex + "_" + z);
		}
		settings.tickets.push(ticketIndex);
		if(sessionTicketNumbers == ''){
			if(preSelectedNumbers == true){
				quickPickExceptPreselected('#quickPick_'+ticketIndex);
			} else {
				quickPick('#quickPick_'+ticketIndex);
			}
		}
	}
}

function clearButtonExceptPreselected(id){
    id = id.match(/\d+/);
	var ticketID = "ticket_"+id;
	if($("#"+ticketID).hasClass('ticketComplete')) {
		settings.completedTicketCount--;
		getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
	}
    for( var j = 0; j < settings.selectedTicketNumbers.length; j++){
        if(id == settings.selectedTicketNumbers[j].index){
            for(var k=0;k < settings.selectedTicketNumbers[j].Numbers.length; k++){
                $("#ticketNumber_"+id+"_"+settings.selectedTicketNumbers[j].Numbers[k]).removeClass("selectedNumber");
            }
			settings.selectedTicketNumbers[j].Numbers = [];
        }
    }
	$("#webUpperTicketSection #clear_"+id).addClass("accountSubmitButtonInactive");
    $("#quickPick_"+id).show();
    $("#complete_"+id).hide();
    $('#lines_' + id).find(".ticketComplete").removeClass("ticketComplete");
    $("#availableNumbers_"+id).removeClass("availableNumbersComplete");
	showNumber(id,{},true);
}

function quickPickExceptPreselected(id){
    var bonusNumberSelected = false;
    var numberSelected = false;
    var hasTicketMatch = false;
    var subStr = id.match("quickPick_(.*)");
    var ticket = subStr[1];
    var nums =[];
    var bonus =[];
    var i = 0;
    var index = 0;
    for ( i = 0; i < settings.selectedTicketNumbers.length; ++i) {
        var array = settings.selectedTicketNumbers[i];
        if(array.index == ticket){ // the ticket is already in the array
            if(array.Numbers.length == settings.PickBallNumber){
                numberSelected = true;
            }
            if(array.BonusNumbers.length == settings.BonusBallNumber) {
                bonusNumberSelected = true;
            }
            index = i;
            hasTicketMatch = true;
            break; 
        }
    }
    if(hasTicketMatch){
		//working on existing ticket 
		if(!numberSelected){
			nums =  new NumberPicker(settings, false).getOtherNumbers(settings.selectedTicketNumbers[index].Numbers);
			settings.selectedTicketNumbers[index].Numbers = [];
			for ( i = 0; i < nums.length; i++){
				settings.selectedTicketNumbers[index].Numbers.push(nums[i]);
			}	 
         }
         if(!bonusNumberSelected){
			bonus =  new NumberPicker(settings, true).getOtherNumbers(settings.selectedTicketNumbers[index].BonusNumbers);
			settings.selectedTicketNumbers[index].BonusNumbers = [];
			for ( i = 0; i < bonus.length; i++){
				settings.selectedTicketNumbers[index].BonusNumbers.push(bonus[i]);
			}	 
         }
    } else{
        //new ticket 
		nums =  new NumberPicker(settings, false).getNumbers();
		bonus = [ticket];
        settings.selectedTicketNumbers.push({index:ticket,Numbers:nums,BonusNumbers:bonus});
    }
	var index2 = '';
	//change selected number color  
	for ( i = 0; i < nums.length; i++){
		index2 = "ticketNumber_" + ticket + "_" + nums[i];
		$("#"+index2).addClass("selectedNumber");
	}	 
	for ( i = 0; i < bonus.length; i++){
		index2 = "bonusTicketNumber_" + ticket + "_" + bonus[i];
		$("#"+index2).addClass("selectedNumber");
	}
	$("#webUpperTicketSection #clear_"+ticket).removeClass("accountSubmitButtonInactive");
	$("#ticket_"+ticket).addClass("ticketComplete");
	$("#complete_"+ticket).show();
	settings.completedTicketCount++;
	getSingleTicketPrice(unitPrice,baseSingleTicketPrice);
	$("#quickPick_"+ticket).hide();
    var currentIndex = settings.selectedTicketNumbers.map(function (i) { return i.index; }).indexOf(ticket);
    if(settings.selectedTicketNumbers[currentIndex].Numbers.length == settings.PickBallNumber){
        $("#availableNumbers_"+ticket).addClass("availableNumbersComplete");
    } 
    if(settings.selectedTicketNumbers[currentIndex].BonusNumbers.length == settings.BonusBallNumber){
        $("#availableBonusNumbers_"+ticket).addClass("availableBonusNumbersComplete");
    }
    showNumber(ticket,settings.selectedTicketNumbers[currentIndex],false);
}

$("#placePromoButton").click(function(e){
    if(settings.completedTicketCount >= settings.minTicketCount){
        if(settings.tickets.length  == settings.completedTicketCount){
			var ticketNumbersString = JSON.stringify(settings.selectedTicketNumbers);
			$("#jsonTicketNumbers").val(ticketNumbersString);
        } else {
            var r = alert("You have incomplete tickets. You must complete all " + settings.tickets.length + " tickets before continuing");
            e.preventDefault();
        }
    } else {
		e.preventDefault();
        alert("You have incomplete tickets. You must complete all " + settings.tickets.length + " tickets before continuing");
    }
});
  
$("#clearAllExceptPreselected").on('click', function(){
	completedTickets = new Array();
	for( var j = 0; j < settings.selectedTicketNumbers.length; ++j){
		completedTickets.push(settings.selectedTicketNumbers[j].index); 
	}
	for(var k=0;k<completedTickets.length;k++){
		clearButtonExceptPreselected("clear_"+completedTickets[k]); 
	}
});
		
$("#quickPickExceptPreselected").on('click', function(){
	for( var j = 0; j < settings.selectedTicketNumbers.length; ++j){
		if(settings.selectedTicketNumbers[j].Numbers.length != settings.PickBallNumber){
			quickPickExceptPreselected("quickPick_"+settings.tickets[j]);
		}
	}
});
